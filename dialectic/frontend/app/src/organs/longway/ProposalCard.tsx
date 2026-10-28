import { useId, useState } from 'react'
import { api } from '../../lib/api'
import { notifyLongwayChanged } from './api'
import type { ChartProposal, ScoutedProposal } from './types'

type Proposal = Pick<ChartProposal, 'id' | 'claim' | 'support' | 'review' | 'url' | 'publisher'> & Partial<ScoutedProposal> & { field_mark_id?: string | null }

/** The Field and the chart share both the reading gate and the review door. */
export function ProposalCard({ proposal, roomId, refresh, compact = false }: {
  proposal: Proposal; roomId: string; refresh?: () => void; compact?: boolean
}) {
  // ponytail: opening the link is a device-local reading nudge, not proof of reading.
  const [openedUrl, setOpenedUrl] = useState<string | null>(null)
  const [action, setAction] = useState<'contest' | 'correct' | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const reasonId = useId()
  const [now] = useState(Date.now)
  const paled = proposal.review === 'proposed' && !proposal.written_sid && Boolean(proposal.created_at && now - Date.parse(proposal.created_at) > 14 * 86400000)
  const reason = proposal.requires_counter ? 'Load-bearing claim: no contrary search yet'
    : openedUrl !== proposal.url ? 'Open the page first'
      : proposal.review === 'confirmed' ? 'Confirmed, waiting to be written' : null
  async function review(verb: 'confirm' | 'contest' | 'correct') {
    if (busy || (verb === 'confirm' && reason) || (verb !== 'confirm' && !note.trim())) return
    setBusy(true); setError('')
    const subjects = [{ entity: 'longway_evidence_proposals', id: proposal.id, field: null }]
    try {
      let markId = proposal.field_mark_id
      if (!markId) {
        const existing = await api.getFieldMarks(roomId)
        const active = existing.marks?.find(mark => mark.relation === 'evidence_attachment' && mark.review !== 'superseded' && mark.subjects.some(subject => subject.entity === 'longway_evidence_proposals' && subject.id === proposal.id))
        const mark = active ?? await api.createFieldMark(roomId, {
          relation: 'evidence_attachment', subjects: [{ entity: 'longway_evidence_proposals', id: proposal.id }],
          title: proposal.claim, payload: { url: proposal.url, scope: proposal.scope },
        })
        markId = mark.id
      }
      await api.postFieldReview(roomId, markId.replace(/^field_mark:/, ''), {
        action: verb, ...(verb !== 'confirm' ? { note: note.trim() } : {}),
        ...(verb === 'correct' ? { replacement: { relation: 'evidence_attachment', subjects, title: note.trim(), payload: { claim: note.trim(), url: proposal.url, scope: proposal.scope } } } : {}),
      })
      setAction(null); setNote(''); notifyLongwayChanged(roomId); refresh?.()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not record review') }
    finally { setBusy(false) }
  }
  const fields = [
    ['Applies', [proposal.applies_from, proposal.applies_to].filter(Boolean).join(' to ')],
    ['Direction', proposal.direction], ['Passport', proposal.passport], ['Vehicle', proposal.vehicle],
    ['Leg', [proposal.leg_from, proposal.leg_to].filter(Boolean).join(' to ')],
  ].filter(([, value]) => value)
  return <article className={`longway-card longway-proposal${paled ? ' paled' : ''}`} aria-label={proposal.claim}>
    {proposal.support && <blockquote>{proposal.support}</blockquote>}
    <h3>{proposal.claim}</h3>
    {proposal.scope && <p>{proposal.scope}</p>}
    {fields.length > 0 && <dl className="longway-proposal-scope">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
    {proposal.question_text && <p>answers: {proposal.question_text}</p>}
    <p>{proposal.publisher && <span>{proposal.publisher} · </span>}{/^https?:\/\//i.test(proposal.url) && <a href={proposal.url} target="_blank" rel="noopener noreferrer" onClick={() => setOpenedUrl(proposal.url)} onAuxClick={e => { if (e.button === 1) setOpenedUrl(proposal.url) }}>Open page</a>}</p>
    <p>{proposal.written_sid ? `Written as ${proposal.written_sid}, commit ${proposal.written_commit?.slice(0, 7) ?? 'unknown'}` : proposal.review === 'confirmed' ? 'confirmed, waiting to be written' : proposal.review}</p>
    {!proposal.written_sid && <>
      <div className="longway-actions"><button type="button" disabled={busy || Boolean(reason)} aria-describedby={reason ? reasonId : undefined} onClick={() => void review('confirm')}>Confirm</button>
        <button type="button" disabled={busy} onClick={() => { setAction('contest'); setNote('') }}>Contest</button>
        {!compact && <button type="button" disabled={busy} onClick={() => { setAction('correct'); setNote('') }}>Correct</button>}
      </div>
      {reason && <p id={reasonId} className="longway-review-reason">{reason}</p>}
      {action && <form onSubmit={e => { e.preventDefault(); void review(action) }}><label>{action === 'contest' ? 'Contest note' : 'Better claim'}<input required value={note} onChange={e => setNote(e.target.value)} /></label>
        <div className="longway-actions"><button disabled={busy || !note.trim()}>Save {action}</button><button type="button" disabled={busy} onClick={() => setAction(null)}>Cancel</button></div></form>}
    </>}
    {error && <p role="alert">{error}</p>}
  </article>
}
