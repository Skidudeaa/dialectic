import { ProposalCard } from '../ProposalCard'
import type { ChartProposal, EvidenceRow, Ink, Journey, Season } from '../types'
import './chart.css'

const INK: Record<Ink, string> = {
  pencil: 'An idea. Nothing about this leg has been checked.',
  dotted: 'A source describes this leg, but nobody has checked it yet.',
  dashed: 'A checked source says a service runs or is offered here. Dates, tickets and quality are not confirmed.',
  heavy: 'Booked, and confirmed by everyone it binds. Nothing is yet.',
  contradicted: 'A source contradicts this leg.',
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
type Sources = Record<string, EvidenceRow>
const day = (s: string | null) => s ? new Date(`${s}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : ''

function Line({ ink, x1, x2 }: { ink: Ink; x1: number; x2: number }) {
  return ink === 'pencil' ? <g className="ink-pencil"><line x1={x1} y1={5.4} x2={x2} y2={4.7} /><line x1={x1} y1={4.5} x2={x2} y2={5.3} /></g>
    : <line className={`ink-${ink}`} x1={x1} y1={5} x2={x2} y2={5} />
}

const KEY: [Ink, string][] = [['heavy', 'Booked'], ['dashed', 'Checked source'], ['dotted', 'Unchecked source'], ['pencil', 'Idea only'], ['contradicted', 'Contradicted']]

/** The globe's key: only the inks it is drawing now, so it never explains a line nobody can see. */
export function InkKey({ inks, myth = false }: { inks: Set<Ink>; myth?: boolean }) {
  const shown = KEY.filter(([ink]) => inks.has(ink) && !(myth && (ink === 'pencil' || ink === 'dotted')))
  if (!shown.length) return null
  return <ul className="longway-chart-ui lw-key" aria-label="How routes are drawn">{shown.map(([ink, label]) => <li key={ink} title={INK[ink]}>
    <svg viewBox="0 0 28 10" width="28" height="10" aria-hidden="true"><Line ink={ink} x1={1} x2={27} /></svg>{label}
  </li>)}</ul>
}

/** The page's list strip, available to the shell without importing MapLibre. */
export function JourneyStrip({ journey }: { journey: Journey }) {
  const n = journey.segments.length, gap = 4, len = n ? (96 - gap * (n - 1)) / n : 0
  return <span className="longway-journey-strip"><svg className="longway-chart-ui strip" viewBox="0 0 96 10" width="96" height="10" aria-label={journey.segments.map(s => `${s.from} to ${s.to}: ${s.proposed ? 'proposed. ' : ''}${INK[s.ink]}`).join(' ')} role="img">
    {journey.segments.map((s, i) => <Line key={i} ink={s.proposed ? 'dotted' : s.ink} x1={i * (len + gap)} x2={i * (len + gap) + len} />)}
  </svg>{journey.segments.some(s => s.proposed) && <span className="longway-proposed-tag">proposed</span>}</span>
}

function Evidence({ ids, sources }: { ids: string[]; sources: Sources }) {
  return <ul className="ev">{ids.map(id => {
    const e = sources[id]
    if (!e) return null
    const how = e.status === 'verified' ? `checked ${day(e.checked_at)}` : e.status === 'unverified' ? 'not yet checked' : e.status
    return <li key={id} className={e.faded ? 'faded' : undefined}>
      <b>{id}</b> {e.claim} <span className="small muted">({how}{e.publisher ? `; ${e.publisher}` : ''}{e.scope ? `. Scope: ${e.scope}` : ''}){e.faded ? ' — past its recheck rule' : ''}</span>
      {e.url && /^https?:\/\//.test(e.url) && <> <a href={e.url} target="_blank" rel="noopener noreferrer">Source</a></>}
    </li>
  })}</ul>
}

export function LegCard({ journey, index, sources, onDiscuss, proposals = [], roomId, refresh }: {
  journey: Journey; index: number; sources: Sources; onDiscuss?: (slug: string, index: number) => void
  proposals?: ChartProposal[]; roomId?: string; refresh?: () => void
}) {
  const leg = journey.segments[index]
  if (!leg) return null
  return <article className="longway-chart-ui leg-card" aria-label={`${leg.from} to ${leg.to}`} tabIndex={0}>
    <div className="lg"><svg viewBox="0 0 44 10" width="44" height="10" aria-hidden="true"><Line ink={leg.proposed ? 'dotted' : leg.ink} x1={2} x2={42} /></svg><b>{leg.from} to {leg.to}</b>{leg.proposed && <span className="longway-proposed-tag">proposed</span>}</div>
    <p className="small">{INK[leg.ink]}</p>
    {leg.basis.length > 0 && <details open><summary>Evidence {leg.basis.join(', ')}</summary><Evidence ids={leg.basis} sources={sources} /></details>}
    {roomId && proposals.filter(p => (p.review === 'proposed' || p.review === 'confirmed') && ((p.leg_from === leg.from && p.leg_to === leg.to) || (p.leg_from === leg.to && p.leg_to === leg.from))).map(p => <ProposalCard key={`${roomId}:${p.id}`} proposal={p} roomId={roomId} refresh={refresh} compact />)}
    {onDiscuss && <button type="button" className="discuss" onClick={() => onDiscuss(journey.slug, index)}>Discuss this leg</button>}
  </article>
}

export function SeasonStrip({ season, sources }: { season: Season | null; sources: Sources }) {
  if (!season) return <p className="longway-chart-ui small">No season recorded.</p>
  const est = season.basis === 'hypothesis'
  const cls = (m: number) => season.good.includes(m) ? 'good' : season.possible.includes(m) ? 'possible' : season.avoid.includes(m) ? 'avoid' : ''
  const said = (['good', 'possible', 'avoid'] as const).map(k => `${k}: ${season[k].map(m => MONTHS[m - 1]).join(', ') || 'none'}`).join('; ')
  return <div className="longway-chart-ui season">
    <div className={`months${est ? ' est' : ''}`} role="img" aria-label={said}>{MONTHS.map((m, i) => <span key={m} title={m} className={`m ${cls(i + 1)}`}>{m[0]}</span>)}</div>
    <p className="small">{season.basis === 'hypothesis' ? 'An estimate, not checked.' : `From ${season.basis.join(', ')}.`} {season.note}</p>
    <p className="small muted key"><span className="m good" />good <span className="m possible" />possible <span className="m avoid">x</span>avoid{est ? '. Hatched: an estimate.' : ''}</p>
    {season.basis !== 'hypothesis' && <details><summary>Evidence {season.basis.join(', ')}</summary><Evidence ids={season.basis} sources={sources} /></details>}
  </div>
}
