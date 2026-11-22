import { useState } from 'react'
import type { FormEvent } from 'react'
import type { JourneyNotes } from '../../hooks/useJourneyNotes'
import type { FriendNote } from './types'
import { VoyageDialog } from './voyage/VoyageDialog'

export interface FilmStop { id: string; name: string | null }
type Kind = FriendNote['kind']
const labels = { place: 'Add a place', thought: 'Add a thought' }

export function FriendActions({ notes, title, stop, onOpen, onSent }: {
  notes?: JourneyNotes
  title: string
  stop?: FilmStop | null
  onOpen?: () => void
  onSent: (message: string) => void
}) {
  const [draft, setDraft] = useState<{ kind: Kind; stop: FilmStop | null } | null>(null)
  function open(kind: Kind) {
    onOpen?.()
    setDraft({ kind, stop: kind === 'thought' ? stop ?? null : null })
  }
  return <>
    {(['place', 'thought'] as const).map(kind => <button key={kind} disabled={notes?.data?.writable === false}
      onClick={() => open(kind)}>{labels[kind]}</button>)}
    {draft && <Composer kind={draft.kind} stop={draft.stop} title={title} notes={notes} close={() => setDraft(null)}
      onSent={() => {
        setDraft(null)
        onSent(draft.kind === 'place' ? 'The Scout will look into your place overnight.' : 'Your thought has been added.')
      }} />}
  </>
}

function Composer({ kind, title, stop, notes, close, onSent }: {
  kind: Kind; title: string; stop: FilmStop | null; notes?: JourneyNotes; close: () => void; onSent: () => void
}) {
  const [aboutStop, setAboutStop] = useState(Boolean(stop))
  const [place, setPlace] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const ready = notes?.data?.writable && text.trim() && (kind === 'thought' || place.trim())
  async function send(event: FormEvent) {
    event.preventDefault()
    if (!ready || sending) return
    setSending(true)
    setError('')
    try {
      await notes.add({ kind, text: text.trim(), place: kind === 'place' ? place.trim() : null, about: aboutStop ? stop?.id ?? null : null })
      onSent()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send.')
    } finally { setSending(false) }
  }
  const stopLabel = stop?.name ? 'About ' + stop.name : 'About this stop'
  return <VoyageDialog label={labels[kind]} className="lw-voyage-editor lw-friend-panel" close={() => { if (!sending) close() }}>
    <header><h2>{labels[kind]}</h2><button disabled={sending} onClick={close}>Close</button></header>
    <p className="lw-meta">{title}</p>
    <form onSubmit={send}>
      <fieldset disabled={sending || notes?.data?.writable === false}>
        {stop && <div className="lw-thought-about">
          <p>{aboutStop ? stopLabel : 'About the whole journey'}</p>
          <button type="button" onClick={() => setAboutStop(!aboutStop)}>{aboutStop ? 'About the whole journey' : stopLabel}</button>
        </div>}
        {kind === 'place' && <label>Where?<input autoFocus value={place} onChange={e => setPlace(e.target.value)} /></label>}
        <label>{kind === 'place' ? 'Why this place?' : 'Your thought'}
          <textarea autoFocus={kind === 'thought'} rows={4} value={text} onChange={e => setText(e.target.value)} />
        </label>
      </fieldset>
      {notes?.error && <p role="alert">{notes.error} <button type="button" onClick={notes.refresh}>Retry</button></p>}
      {notes?.data?.writable === false && <p>{notes.data.why || 'Adding is closed.'}</p>}
      {error && <p role="alert">{error}</p>}
      <button className="lw-primary" disabled={!ready || sending}>{sending ? 'Sending…' : 'Send'}</button>
    </form>
  </VoyageDialog>
}
