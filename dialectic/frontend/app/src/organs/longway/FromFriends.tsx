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

function safePhotoUrl(url?: string | null) {
  if (!url) return null
  const trimmed = url.trim()
  if (!trimmed || /^(javascript|data|vbscript):/i.test(trimmed)) return null
  return trimmed
}

export function FromFriends({ roomId, journey, notes }: {
  roomId: string; journey: Pick<Journey, 'title' | 'slug' | 'voyage'>; notes: JourneyNotes
}) {
  const [preview, setPreview] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [started, setStarted] = useState(false)
  const [error, setError] = useState('')
  const book = notes.data
  const hasOpenPlace = Boolean(book?.notes.some(note => note.kind === 'place' && note.state === 'open'))
  async function scout() {
    setSending(true)
    setStarted(false)
    setError('')
    try { await notes.scout(); setStarted(true) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not send the Scout.') }
    finally { setSending(false) }
  }
  return <section className="lw-from-friends" aria-label="From friends">
    <div className="lw-from-friends-head">
      <h2>From friends</h2>
      {book && book.notes.length > 0 && <span className="lw-count">{book.notes.length}</span>}
    </div>
    {notes.error && <p role="alert" className="lw-alert">{notes.error} <button onClick={notes.refresh}>Retry</button></p>}
    {!book && !notes.error && <p className="lw-note">Loading contributions…</p>}
    {book?.notes.length === 0 && <p className="lw-note lw-empty-friends">No places or thoughts yet.</p>}
    {book && book.notes.length > 0 && <div className="lw-friend-list">
      {book.notes.map(note => <article key={note.id} className="lw-friend-note" data-kind={note.kind} data-state={note.state}>
        <p className="lw-friend-by">{note.by} · <time dateTime={note.at}>{date.format(new Date(note.at))}</time></p>
        {note.kind === 'place' && <h3 className="lw-friend-place">{note.place}</h3>}
        <p className="lw-friend-words longway-plan">{note.text}</p>
        {note.kind === 'place' && <div className="lw-friend-foot">
          {note.steer && note.state === 'open' && <p className="lw-friend-steer">Sent back to the Scout by {note.steer.by}: {note.steer.text}</p>}
          <p className="lw-friend-status" data-state={note.state}>{statusLine[note.state]}</p>
          {note.note && note.state !== 'accepted' && <p className="lw-friend-scout-note">{note.note}</p>}
          {book.can_review && note.state === 'drafted' && <ReviewPlace notes={notes} note={note} preview={() => setPreview(note.id)} />}
        </div>}
      </article>)}
    </div>}
    {book?.can_review && <>
      {(hasOpenPlace || started || error) && <div className="lw-scout-bar">
        {hasOpenPlace && <button className="lw-scout-btn" disabled={sending} onClick={() => void scout()}>Send the Scout now</button>}
        {started && <p role="status" className="lw-note">The Scout run has started.</p>}
        {error && <p role="alert" className="lw-alert">{error}</p>}
      </div>}
      {preview && <VoyageStage roomId={roomId} journey={journey} notes={notes} preview={preview} close={() => setPreview(null)} />}
    </>}
  </section>
}

function ReviewPlace({ note, notes, preview }: { note: FriendNote; notes: JourneyNotes; preview: () => void }) {
  const [mode, setMode] = useState<'send-back' | 'set-aside' | null>(null)
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const draft = note.draft
  const photoUrl = safePhotoUrl(draft?.photo?.url)
  async function decide(decision: 'accept' | 'send-back' | 'set-aside') {
    const reason = why.trim()
    if (decision === 'send-back' && !reason) return
    setBusy(true)
    setError('')
    try {
      await notes.review(note.id, decision, decision === 'accept' ? '' : reason)
      setMode(null)
      setWhy('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the decision.')
    } finally { setBusy(false) }
  }
  function openMode(next: 'send-back' | 'set-aside') {
    setMode(next)
    setWhy('')
    setError('')
  }
  return <div className="lw-friend-review">
    {draft && <div className={photoUrl ? 'lw-draft-plate has-photo' : 'lw-draft-plate'}>
      {draft.photo && (photoUrl
        ? <figure className="lw-draft-figure">
          <img className="lw-draft-photo" src={photoUrl} alt={draft.name} loading="lazy" />
          <figcaption className="lw-draft-credit">Photograph by {draft.photo.author} · {draft.photo.licence}</figcaption>
        </figure>
        : <p className="lw-draft-credit">Photograph by {draft.photo.author} · {draft.photo.licence}</p>)}
      <div className="lw-draft-copy">
        {draft.kicker && <p className="lw-draft-kicker">{draft.kicker}</p>}
        <h4 className="lw-draft-name">{draft.name}</h4>
        {draft.moment?.text && <p className="lw-draft-moment">{draft.moment.text}</p>}
      </div>
    </div>}
    {mode === 'send-back' ? <form className="lw-draft-reason-form" onSubmit={e => { e.preventDefault(); void decide('send-back') }}>
      <label className="lw-field">What should change?<input autoFocus disabled={busy} value={why} onChange={e => setWhy(e.target.value)} /></label>
      <div className="lw-draft-actions">
        <button className="lw-primary" disabled={busy || !why.trim()}>Send back</button>
        <button type="button" className="lw-quiet-btn" disabled={busy} onClick={() => { setMode(null); setWhy(''); setError('') }}>Cancel</button>
      </div>
    </form> : mode === 'set-aside' ? <form className="lw-draft-reason-form" onSubmit={e => { e.preventDefault(); void decide('set-aside') }}>
      <label className="lw-field">Reason (optional)<input autoFocus disabled={busy} value={why} onChange={e => setWhy(e.target.value)} /></label>
      <div className="lw-draft-actions">
        <button className="lw-primary" disabled={busy}>Set aside</button>
        <button type="button" className="lw-quiet-btn" disabled={busy} onClick={() => { setMode(null); setWhy(''); setError('') }}>Cancel</button>
      </div>
    </form> : <div className="lw-draft-actions">
      <button className="lw-primary" disabled={busy} onClick={() => void decide('accept')}>Accept</button>
      <button className="lw-draft-preview-btn" onClick={preview}>See it in the film</button>
      <button className="lw-draft-back-btn" disabled={busy} onClick={() => openMode('send-back')}>Send back</button>
      <button className="lw-draft-aside-btn" disabled={busy} onClick={() => openMode('set-aside')}>Set aside</button>
    </div>}
    {error && <p role="alert" className="lw-alert">{error}</p>}
  </div>
}
