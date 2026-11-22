import { useState } from 'react'
import type { JourneyNotes } from '../../hooks/useJourneyNotes'
import type { FriendNote, Journey } from './types'
import { VoyageStage } from './voyage/VoyageStage'

const statusLine: Record<FriendNote['state'], string> = {
  open: 'New. The Scout will look into it.',
  drafted: 'The Scout has drafted this stop. Waiting for a house manager.',
  accepted: 'In the journey.',
  'set aside': 'Set aside.',
}
const date = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })

export function FromFriends({ roomId, journey, notes }: {
  roomId: string; journey: Pick<Journey, 'title' | 'slug' | 'voyage'>; notes: JourneyNotes
}) {
  const [preview, setPreview] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [started, setStarted] = useState(false)
  const [error, setError] = useState('')
  const book = notes.data
  async function scout() {
    setSending(true)
    setStarted(false)
    setError('')
    try { await notes.scout(); setStarted(true) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not send the Scout.') }
    finally { setSending(false) }
  }
  return <section className="lw-from-friends" aria-label="From friends">
    <h2>From friends</h2>
    {notes.error && <p role="alert">{notes.error} <button onClick={notes.refresh}>Retry</button></p>}
    {!book && !notes.error && <p className="lw-note">Loading contributions…</p>}
    {book?.notes.length === 0 && <p className="lw-note">No places or thoughts yet.</p>}
    {book?.notes.map(note => <article key={note.id}>
      <p className="lw-meta">{note.by} · <time dateTime={note.at}>{date.format(new Date(note.at))}</time></p>
      {note.kind === 'place' && <h3>{note.place}</h3>}
      <p className="longway-plan">{note.text}</p>
      {note.kind === 'place' && <>
        <p className="lw-note">{statusLine[note.state]}</p>
        {note.note && note.state !== 'accepted' && <p className="lw-note">{note.note}</p>}
        {book.can_review && note.state === 'drafted' && <ReviewPlace notes={notes} note={note} preview={() => setPreview(note.id)} />}
      </>}
    </article>)}
    {book?.can_review && <>
      {book.notes.some(note => note.kind === 'place' && note.state === 'open') && <button
        disabled={sending} onClick={() => void scout()}>Send the Scout now</button>}
      {started && <p role="status" className="lw-note">The Scout run has started.</p>}
      {error && <p role="alert">{error}</p>}
      {preview && <VoyageStage roomId={roomId} journey={journey} notes={notes} preview={preview} close={() => setPreview(null)} />}
    </>}
  </section>
}

function ReviewPlace({ note, notes, preview }: { note: FriendNote; notes: JourneyNotes; preview: () => void }) {
  const [asking, setAsking] = useState(false)
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const draft = note.draft
  async function decide(decision: 'accept' | 'set-aside') {
    setBusy(true)
    setError('')
    try { await notes.review(note.id, decision, decision === 'set-aside' ? why.trim() : '') }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not save the decision.') }
    finally { setBusy(false) }
  }
  return <div className="lw-friend-review">
    {draft && <>
      <h4>{draft.name}</h4>
      {draft.kicker && <p className="lw-meta">{draft.kicker}</p>}
      {draft.moment?.text && <p>{draft.moment.text}</p>}
      {draft.photo && <p className="lw-note">Photograph by {draft.photo.author} · {draft.photo.licence}</p>}
    </>}
    {asking ? <form onSubmit={e => { e.preventDefault(); void decide('set-aside') }}>
      <label>Reason (optional)<input autoFocus disabled={busy} value={why} onChange={e => setWhy(e.target.value)} /></label>
      <div className="longway-actions"><button disabled={busy}>Set aside</button>
        <button type="button" disabled={busy} onClick={() => setAsking(false)}>Cancel</button></div>
    </form> : <div className="longway-actions">
      <button onClick={preview}>See it in the film</button>
      <button disabled={busy} onClick={() => void decide('accept')}>Accept</button>
      <button disabled={busy} onClick={() => setAsking(true)}>Set aside</button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </div>
}
