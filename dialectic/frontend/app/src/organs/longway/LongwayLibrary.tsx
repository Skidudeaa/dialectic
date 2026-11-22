import { useJourneyNotes } from '../../hooks/useJourneyNotes'
import { FromFriends } from './FromFriends'
import { VoyageActions } from './voyage/VoyageActions'
import { memo, useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useLongwayJourney } from '../../hooks/useLongwayJourney'
import { cleanPull } from './pull'
import type { JourneyDetail, Season } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function monthRuns(months: number[]): string {
  const sorted = [...new Set(months)].filter(m => m >= 1 && m <= 12).sort((a, b) => a - b)
  const runs: [number, number][] = []
  for (const m of sorted) {
    const last = runs[runs.length - 1]
    if (last && m === last[1] + 1) last[1] = m
    else runs.push([m, m])
  }
  if (runs.length > 1 && runs[0][0] === 1 && runs[runs.length - 1][1] === 12) {
    const first = runs.shift()!
    runs[runs.length - 1][1] = first[1]
  }
  return runs.map(([a, b]) => a === b ? MONTHS[a - 1] : `${MONTHS[a - 1]}–${MONTHS[b - 1]}`).join(', ')
}

function seasonLine(season: Season | null) {
  if (!season) return null
  const said = season.good.length ? `Best ${monthRuns(season.good)}` : season.possible.length ? `Possible ${monthRuns(season.possible)}` : null
  return said && (season.basis === 'hypothesis' ? `${said} (estimate)` : said)
}

function journeyMeta(journey: JourneyDetail) {
  const days = journey.days && (journey.days[0] === journey.days[1] ? `${journey.days[0]} days` : `${journey.days[0]}–${journey.days[1]} days`)
  return [journey.where, days, seasonLine(journey.season)].filter(Boolean).join(' · ')
}

function renderMarkdown(markdown: string) {
  return DOMPurify.sanitize(marked.parse(markdown, { async: false }))
}

/** Separate the dossier's opening Pull paragraph (shown cleanly in the hero) from the full record. */
function splitDossier(markdown: string, title: string) {
  let body = markdown.trim()
  let customHeading = ''
  const h1 = body.match(/^#\s+([^\n]+)(?:\n+|$)/)
  if (h1) {
    const text = h1[1].trim()
    body = body.slice(h1[0].length).trim()
    if (text.toLowerCase() !== title.trim().toLowerCase()) customHeading = `# ${text}`
  }
  const pull = body.match(/(?:^|\n)##\s+The pull\s*\n+([^\n][\s\S]*?)(?:\n{2,}|$)/i)
  const lead = pull ? pull[1].trim() : ''
  const isLong = body.length > 0 && (Boolean(pull) || body.includes('\n## '))
  return { customHeading, lead, body, isLong }
}

// Keep the reading surface (and any text selection) intact when contributions change.
const Dossier = memo(function Dossier({ markdown, title }: { markdown: string; title: string }) {
  const { customHeading, body, isLong } = useMemo(() => splitDossier(markdown, title), [markdown, title])
  const headingHtml = useMemo(() => customHeading ? renderMarkdown(customHeading) : '', [customHeading])
  const bodyHtml = useMemo(() => body ? renderMarkdown(body) : '', [body])
  if (!headingHtml && !bodyHtml) return <section aria-label="Dossier" className="lw-dossier-panel" />
  return <section aria-label="Dossier" className="lw-dossier-panel">
    {headingHtml && <div className="lw-dossier-custom-head" dangerouslySetInnerHTML={{ __html: headingHtml }} />}
    {isLong ? <>
      <div className="lw-dossier-card-head">
        <h2>Dossier</h2>
      </div>
      <details className="lw-dossier-disclosure">
        <summary>Read the full dossier</summary>
        <div className="lw-dossier-body" dangerouslySetInnerHTML={{ __html: bodyHtml }} />
      </details>
    </> : bodyHtml ? <div className="lw-dossier-body" dangerouslySetInnerHTML={{ __html: bodyHtml }} /> : null}
  </section>
})

const HeroLead = memo(function HeroLead({ markdown, fallback }: { markdown: string; fallback?: string }) {
  const html = useMemo(() => markdown ? renderMarkdown(markdown) : '', [markdown])
  if (html) return <div className="lw-hero-lead" dangerouslySetInnerHTML={{ __html: html }} />
  if (fallback) return <p className="lw-hero-lead">{fallback}</p>
  return null
})

export function LongwayLibrary({ roomId }: { roomId: string }) {
  const { data, error, loading, unbound, hasVoyage, canEdit, refresh } = useLongwayJourney(roomId)
  const notes = useJourneyNotes(roomId, data?.slug)
  const lead = useMemo(() => data ? cleanPull(splitDossier(data.dossier, data.title).lead) : '', [data])
  const fallbackPull = useMemo(() => data?.pull ? cleanPull(data.pull) : '', [data])
  if (error && !data) return <div className="longway-library scene-body"><p role="alert" className="lw-alert">{error} <button onClick={refresh}>Retry journey</button></p></div>
  if (unbound) return <div className="longway-library scene-body"><p className="lw-note">This room is not yet linked to a journey.</p></div>
  if (loading || !data) return <div className="longway-library scene-body"><p role="status" className="lw-note">Loading journey…</p></div>
  const metaLine = journeyMeta(data)
  return <div className="longway-library scene-body">
    {error && <p role="alert" className="lw-alert">{error} <button onClick={refresh}>Retry journey</button></p>}
    <header className="lw-journey-hero">
      <div className="lw-hero-copy">
        {metaLine && <p className="lw-eyebrow lw-hero-meta">{metaLine}</p>}
        <h1>{data.title}</h1>
        <HeroLead markdown={lead} fallback={fallbackPull} />
      </div>
      <div className="lw-hero-actions">
        <VoyageActions key={data.slug} roomId={roomId} journey={{ slug: data.slug, title: data.title, voyage: hasVoyage }} canEdit={canEdit} notes={notes} library />
      </div>
    </header>
    <div className="lw-library-spread">
      <div className="lw-library-main">
        <FromFriends key={data.slug} roomId={roomId} journey={data} notes={notes} />
      </div>
      <aside className="lw-library-aside">
        <Dossier markdown={data.dossier} title={data.title} />
        <section aria-label="Vehicles" className="lw-library-vehicles">
          <h2>Vehicles{data.vehicles.length > 0 && <>{' '}<span className="lw-count">{data.vehicles.length}</span></>}</h2>
          {data.vehicles.map(vehicle => <article key={vehicle.name} className="longway-card lw-vehicle-card">
            <h3>{vehicle.name}</h3>
            <p className="lw-vehicle-fix">{vehicle.fix ? `heard ${Math.floor(vehicle.fix.age_min)} min ago · ${vehicle.fix.lat}, ${vehicle.fix.lon}${vehicle.fix.place ? ` · ${vehicle.fix.place}` : ''}` : 'never heard'}</p>
            {vehicle.note && <p>{vehicle.note}</p>}
            {vehicle.timetable && <a href={vehicle.timetable} target="_blank" rel="noopener noreferrer">Published timetable</a>}
          </article>)}
        </section>
      </aside>
    </div>
    <section aria-label="Evidence ledger" className="lw-library-evidence">
      <h2>Evidence ledger{data.evidence.length > 0 && <>{' '}<span className="lw-count">{data.evidence.length}</span></>}</h2>
      <div className="lw-evidence-grid">
        {data.evidence.map(row => <article key={row.id} className={`longway-card${row.faded ? ' is-faded' : ''}`}>
          <h3>{row.id} · {row.claim}</h3>
          <p>{row.status}{row.checked_at ? ` · checked ${new Date(`${row.checked_at}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}` : ''}</p>
          {row.faded && <p>past its recheck rule</p>}
          {row.scope && <p>{row.scope}</p>}
          {row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer">{row.publisher ?? row.url}</a> : row.publisher ? <p>{row.publisher}</p> : null}
        </article>)}
      </div>
    </section>
    <h2 className="lw-library-readings-heading">Room readings</h2>
  </div>
}
