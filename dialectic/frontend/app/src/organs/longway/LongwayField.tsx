import { useState } from 'react'
import { api } from '../../lib/api'
import { useLongwayProposals } from '../../hooks/useLongwayProposals'
import type { EvidenceProposal } from './types'

function Proposal({ proposal, roomId, refresh }: { proposal: EvidenceProposal; roomId: string; refresh: () => void }) {
  const [action, setAction] = useState<'contest' | 'correct' | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function review(verb: 'confirm' | 'contest' | 'correct') {
    setBusy(true); setError('')
    const subjects = [{ entity: 'longway_evidence_proposals', id: proposal.id, field: null }]
    try {
      // Creating is idempotent. Review the resulting mark via the shared door;
      // proposal ids are NOT field-mark ids, so they cannot be review targets.
      const existing = await api.getFieldMarks(roomId)
      const active = existing.marks?.find(mark => mark.review !== 'superseded' && mark.subjects.some(subject => subject.entity === 'longway_evidence_proposals' && subject.id === proposal.id))
      const mark = active ?? await api.createFieldMark(roomId, {
        relation: 'evidence_attachment', subjects: [{ entity: 'longway_evidence_proposals', id: proposal.id }],
        title: proposal.claim, payload: { url: proposal.url, scope: proposal.scope },
      })
      await api.postFieldReview(roomId, mark.id, {
        action: verb, ...(verb !== 'confirm' ? { note: note.trim() } : {}),
        ...(verb === 'correct' ? { replacement: { relation: 'evidence_attachment', subjects, title: note.trim(), payload: { claim: note.trim(), url: proposal.url, scope: proposal.scope } } } : {}),
      })
      setAction(null); setNote(''); refresh()
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not record review') }
    finally { setBusy(false) }
  }
  return <article className="longway-card"><h3>{proposal.claim}</h3><a href={proposal.url} target="_blank" rel="noopener noreferrer">{proposal.publisher ?? proposal.url}</a>
    <p>{proposal.scope}</p>{proposal.support && <blockquote>{proposal.support}</blockquote>}
    <p>{proposal.written_sid ? `Written as ${proposal.written_sid}, commit ${proposal.written_commit?.slice(0, 7) ?? 'unknown'}` : proposal.review === 'confirmed' ? 'confirmed, waiting to be written' : proposal.review}</p>
    {!proposal.written_sid && <><div className="longway-actions"><button disabled={busy || proposal.review === 'confirmed'} onClick={() => void review('confirm')}>Confirm</button>
      <button disabled={busy} onClick={() => { setAction('contest'); setNote('') }}>Contest</button><button disabled={busy} onClick={() => { setAction('correct'); setNote('') }}>Correct</button></div>
      {action && <form onSubmit={e => { e.preventDefault(); void review(action) }}><label>{action === 'contest' ? 'What does the page actually say?' : 'Better claim'}<textarea required value={note} onChange={e => setNote(e.target.value)} /></label>
        <button disabled={busy || !note.trim()}>Save {action}</button><button type="button" disabled={busy} onClick={() => setAction(null)}>Cancel</button></form>}
    </>}{error && <p role="alert">{error}</p>}
  </article>
}
export function LongwayField({ roomId }: { roomId: string }) {
  const { data, error, refresh } = useLongwayProposals(roomId)
  return <section className="longway-field scene-body" aria-label="Proposed evidence"><h2>Proposed evidence</h2>
    {error ? <p role="alert">{error} <button onClick={refresh}>Retry proposals</button></p> : !data ? <p role="status">Loading proposals…</p> : data.length === 0 ? <p>No evidence proposed yet.</p> : data.map(proposal => <Proposal key={proposal.id} proposal={proposal} roomId={roomId} refresh={refresh} />)}
  </section>
}
