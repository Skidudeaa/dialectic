import { useEffect, useRef, useState } from 'react'
import type { Journey } from '../types'
import { longwayPath } from '../api'
import { useLongwaySnapshot } from '../useLongwayResource'
import { VoyageDialog } from './VoyageDialog'
import { VoyageEditor } from './VoyageEditor'
import type { Receipt } from './voyage'

type Target = Pick<Journey, 'slug' | 'title' | 'voyage'>
type Props = { roomId: string; journey: Target }

function Saved({ receipt }: { receipt: Receipt }) {
  return <p role="status" className="lw-voyage-saved">Saved <code>{receipt.commit.slice(0, 7)}</code> · {receipt.changed.join(', ')}</p>
}

export function VoyageActions({ roomId, journey, library = false }: Props & { library?: boolean }) {
  const [open, setOpen] = useState<'stage' | 'dossier' | 'record' | null>(null)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  return <>
    {journey.voyage === true && <button onClick={() => setOpen('stage')}>Ride the voyage</button>}
    {library && <><button onClick={() => setOpen('dossier')}>Edit dossier</button>
      <button onClick={() => setOpen('record')}>Edit record</button></>}
    {receipt && <Saved receipt={receipt} />}
    {open === 'stage' && <VoyageStage roomId={roomId} journey={journey} close={() => setOpen(null)} />}
    {(open === 'dossier' || open === 'record') && <VoyageEditor roomId={roomId} journey={journey} initialView={open}
      close={() => setOpen(null)} onSaved={result => { setReceipt(result); setOpen(null) }} />}
  </>
}

interface Stop { id: string; name: string | null }

function VoyageStage({ roomId, journey, close }: Props & { close: () => void }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const [stop, setStop] = useState<Stop | null>(null)
  const [editing, setEditing] = useState<Stop | null>(null)
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const [resume, setResume] = useState({ id: '', revision: 0 })

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return
      const data = event.data
      if (data?.source !== 'longway-voyage') return
      if (data.type === 'escape' && !editing) { close(); return }
      if (data.type !== 'station') return
      if (data.station === null) setStop(null)
      else if (typeof data.station === 'string' && (typeof data.name === 'string' || data.name === null)) {
        setStop({ id: data.station, name: data.name })
      }
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [close, editing])
  function edit() {
    frame.current?.contentWindow?.postMessage({ source: 'longway-house', type: 'pause' }, '*')
    setEditing(stop)
  }
  const path = longwayPath(roomId, `voyage/${encodeURIComponent(journey.slug)}/page`) +
    (resume.id ? `?station=${encodeURIComponent(resume.id)}` : '')
  return <VoyageDialog label={journey.title + ' voyage'} className="lw-voyage-stage" close={close}>
    <header className="lw-voyage-bar">
      <button onClick={close}>The house</button><strong title={journey.title}>{journey.title}</strong>
      {stop?.name && <span title={stop.name}>{stop.name}</span>}
      <button disabled={!stop} onClick={edit}>Edit this stop</button>
    </header>
    {receipt && <Saved receipt={receipt} />}
    <Film key={resume.revision} path={path} title={journey.title} frame={frame} />
    {editing && <VoyageEditor roomId={roomId} journey={journey} station={editing.id} initialView="stop" close={() => setEditing(null)}
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
