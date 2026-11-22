import { useEffect, useRef, useState } from 'react'
import type { Journey } from '../types'
import { longwayPath } from '../api'
import { useLongwaySnapshot } from '../useLongwayResource'
import type { JourneyNotes } from '../../../hooks/useJourneyNotes'
import { FriendActions } from '../FriendActions'
import type { FilmStop } from '../FriendActions'
import { VoyageDialog } from './VoyageDialog'
import { VoyageEditor } from './VoyageEditor'
import type { Receipt } from './voyage'

export function Saved({ receipt }: { receipt: Receipt }) {
  return <p role="status" className="lw-voyage-saved">Saved <code>{receipt.commit.slice(0, 7)}</code> · {receipt.changed.join(', ')}</p>
}

export function VoyageStage({ roomId, journey, canEdit = false, close, preview, notes }: {
  roomId: string; journey: Pick<Journey, 'slug' | 'title' | 'voyage'>; canEdit?: boolean
  close: () => void; preview?: string; notes: JourneyNotes
}) {
  const frame = useRef<HTMLIFrameElement>(null)
  const [stop, setStop] = useState<FilmStop | null>(null)
  const [editing, setEditing] = useState<FilmStop | null>(null)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [message, setMessage] = useState('')
  const [resume, setResume] = useState({ id: '', revision: 0 })

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return
      const data = event.data
      if (data?.source !== 'longway-voyage') return
      if (data.type === 'escape') {
        if (!frame.current.closest('dialog')?.querySelector('dialog[open]')) close()
        return
      }
      if (data.type !== 'station') return
      if (data.station === null) setStop(null)
      else if (typeof data.station === 'string' && (typeof data.name === 'string' || data.name === null)) {
        setStop({ id: data.station, name: data.name })
      }
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [close])
  function pause() {
    frame.current?.contentWindow?.postMessage({ source: 'longway-house', type: 'pause' }, '*')
  }
  function edit() {
    pause()
    setEditing(stop)
  }
  const path = longwayPath(roomId, `voyage/${encodeURIComponent(journey.slug)}/page`) +
    (preview ? `?preview=${encodeURIComponent(preview)}` : resume.id ? `?station=${encodeURIComponent(resume.id)}` : '')
  return <VoyageDialog label={journey.title + ' voyage'} className="lw-voyage-stage" close={close}>
    <header className="lw-voyage-bar">
      <button onClick={close} aria-label="The house"><span className="lw-wide-label">The house</span><span className="lw-short-label">House</span></button><strong title={journey.title}>{journey.title}</strong>
      {stop?.name && <span title={stop.name}>{stop.name}</span>}
      <FriendActions notes={notes} title={journey.title} stop={stop} onOpen={() => { pause(); setMessage('') }} onSent={setMessage} />
      {canEdit && !preview && <button disabled={!stop} onClick={edit} aria-label="Edit this stop"><span className="lw-wide-label">Edit this stop</span><span className="lw-short-label">Edit</span></button>}
    </header>
    {notes.data?.writable === false && <p className="lw-voyage-saved">{notes.data.why || 'Adding is closed.'}</p>}
    {message && <p role="status" className="lw-voyage-saved">{message}</p>}
    {canEdit && receipt && <Saved receipt={receipt} />}
    <Film key={resume.revision} path={path} title={journey.title} frame={frame} />
    {canEdit && editing && <VoyageEditor roomId={roomId} journey={journey} station={editing.id} initialView="stop" close={() => setEditing(null)}
      onSaved={result => {
        setReceipt(result)
        setResume(current => ({ id: editing.id, revision: current.revision + 1 }))
        setStop(null)
        setEditing(null)
      }} />}
  </VoyageDialog>
}

// Keyboard events stop at the opaque browsing context. Append a fixed listener
// after the complete server page so Escape also works after interacting with
// the film. It receives no credentials and needs no access to the parent DOM.
const forwardEscape = `<script>window.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') parent.postMessage({ source: 'longway-voyage', type: 'escape' }, '*')
}, true)</script>`

function Film({ path, title, frame }: { path: string; title: string; frame: React.RefObject<HTMLIFrameElement | null> }) {
  const { data, error, refresh } = useLongwaySnapshot<{ html: string }>(path)
  if (error) return <p role="alert">{error} <button onClick={refresh}>Retry voyage</button></p>
  if (!data) return <p role="status">Loading voyage…</p>
  return <iframe ref={frame} title={title + ' voyage film'} sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
    allow="fullscreen; autoplay" srcDoc={data.html + forwardEscape} />
}
