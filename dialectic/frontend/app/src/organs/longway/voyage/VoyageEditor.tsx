import { useRef, useState } from 'react'
import { longwayPath, longwayRequest, notifyLongwayChanged } from '../api'
import type { Journey } from '../types'
import { useLongwaySnapshot } from '../useLongwayResource'
import { VoyageDialog } from './VoyageDialog'
import { fieldText, fieldValue, isObject, pretty, readField, stopFields, withField } from './voyage'
import type { DocumentName, EditBody, EditorView, Field, JourneyDocument, Json, Receipt, SetOp } from './voyage'

type Props = {
  roomId: string
  journey: Pick<Journey, 'slug' | 'title' | 'voyage'>
  station?: string
  initialView: EditorView
  close: () => void
  onSaved: (receipt: Receipt) => void
}

export function VoyageEditor({ roomId, journey, station, initialView, close, onSaved }: Props) {
  const [view, setView] = useState(initialView)
  const [part, setPart] = useState('')
  const [busy, setBusy] = useState(false)
  const dirty = useRef(false)
  const name: DocumentName = view === 'everything' || view === 'stop' ? 'voyage' : view
  const path = longwayPath(roomId, `document/${encodeURIComponent(journey.slug)}/${name}`)
  const { data, error, refresh } = useLongwaySnapshot<JourneyDocument>(path)
  const whole = name === 'voyage' && isObject(data?.value) ? data.value : {}
  const stations = Array.isArray(whole.stations) ? whole.stations.filter(isObject) : []
  const parts = [
    ...Object.entries(whole).map(([key, value]) => ({ path: key, label: key, value })),
    ...stations.map(stop => ({ path: 'stations/' + stop.id, label: String(stop.name ?? stop.id), value: stop as Json })),
  ]
  const chosen = view === 'stop' ? parts.find(item => item.path === 'stations/' + station) :
    parts.find(item => item.path === part) ?? parts[0]
  function leaveDraft() {
    if (busy || (dirty.current && !window.confirm('Discard your unsaved changes?'))) return false
    dirty.current = false
    return true
  }
  async function save(body: EditBody) {
    setBusy(true)
    try {
      const result = await longwayRequest<Receipt>(path, { method: 'POST', body: JSON.stringify(body) })
      dirty.current = false
      onSaved(result)
      notifyLongwayChanged(roomId)
    } finally { setBusy(false) }
  }
  const finish = () => { if (!busy) close() }
  return <VoyageDialog label={'Edit ' + journey.title} className={'lw-voyage-editor' + (station ? ' on-stage' : '')} close={finish}>
    <header><h2>{view === 'stop' ? chosen?.label ?? 'This stop' : view === 'everything' ? 'The voyage' : view === 'record' ? 'Record' : 'Dossier'}</h2>
      <button disabled={busy} onClick={finish}>Close editor</button></header>
    <label>What to edit<select value={view} disabled={busy} onChange={e => {
      if (leaveDraft()) setView(e.target.value as EditorView)
    }}>
      <option value="stop" disabled={!station}>This stop</option>
      <option value="everything" disabled={!journey.voyage}>Everything in the voyage</option>
      <option value="dossier">Dossier</option><option value="record">Record</option>
    </select></label>
    {error && <p role="alert">{error} <button onClick={refresh}>Retry</button></p>}
    {!data && !error && <p role="status">Loading…</p>}
    {data && <>
      {view === 'everything' && <label>Everything<select value={chosen?.path ?? ''} disabled={busy}
        onChange={e => { if (leaveDraft()) setPart(e.target.value) }}>
        {parts.map(item => <option key={item.path} value={item.path}>{item.label}</option>)}
      </select></label>}
      {!data.writable && <p>{data.why ?? 'Editing is closed.'}</p>}
      {(view === 'stop' || view === 'everything') && !chosen
        ? <p>This stop is unavailable.</p>
        : <DocumentForm key={[path, view, chosen?.path].join(':')} view={view} data={data}
          path={chosen?.path ?? ''} value={name === 'voyage' && chosen ? chosen.value : data.value}
          busy={busy} dirty={() => { dirty.current = true }} save={save} />}
    </>}
  </VoyageDialog>
}

function FieldInput({ field, text, change, readOnly }: {
  field: Field; text: string; change: (text: string) => void; readOnly?: boolean
}) {
  const props = { 'aria-label': field.label, value: text, readOnly, onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => change(e.target.value) }
  return <label>{field.label}
    {field.kind === 'prose' || field.kind === 'json'
      ? <textarea {...props} rows={field.kind === 'json' ? 8 : 3} spellCheck={field.kind !== 'json'} />
      : <input {...props} type={field.kind === 'number' ? 'number' : 'text'} step={field.kind === 'number' ? 'any' : undefined} />}
  </label>
}

function DocumentForm({ view, data, value, path, busy, dirty, save }: {
  view: EditorView; data: JourneyDocument; value: Json; path: string; busy: boolean
  dirty: () => void; save: (body: EditBody) => Promise<void>
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [raw, setRaw] = useState<string | null>(null)
  const [error, setError] = useState('')
  const saving = useRef(false)
  const isStop = view === 'stop'
  const isRecord = view === 'record'
  const readOnly = !data.writable || ((view === 'everything' || isStop) && data.protected.includes(path.split('/')[0]))
  const fields: Field[] = isStop ? stopFields : isRecord && isObject(value) ?
    Object.entries(value).map(([key, v]) => ({ path: key, label: key, kind: typeof v === 'string' ? 'prose' : 'json' })) : []
  const rawField: Field = { path, label: isStop ? 'All fields (JSON)' : path, kind: 'json' }

  // The plain fields and the whole-stop textarea are two views of one draft.
  // Retain the typed text even while it is incomplete or refused by the server.
  let base = value
  let draft = value
  let invalid = ''
  const ops: SetOp[] = []
  function currentValue(field: Field) {
    if (!isObject(base)) return undefined
    return isStop ? readField(base, field.path) : base[field.path]
  }
  try {
    if (raw !== null && view !== 'dossier') base = fieldValue(rawField, raw)
    if (isStop && !isObject(base)) throw new Error('Enter a stop with its fields.')
    draft = base
    for (const field of fields) {
      if (!Object.hasOwn(inputs, field.path) || (isRecord && data.protected.includes(field.path))) continue
      const previous = currentValue(field)
      const text = inputs[field.path]
      if (text === fieldText(previous, field.kind)) continue
      const next = fieldValue(field, text)
      if (JSON.stringify(previous) === JSON.stringify(next)) continue
      ops.push({ op: 'set', path: isStop ? path + '/' + field.path : field.path, value: next })
      if (isStop && isObject(draft)) draft = withField(draft, field.path, next)
    }
  } catch (err) { invalid = (err as Error).message }

  function changeRaw(text: string) {
    setRaw(text)
    setInputs({})
    setError('')
    dirty()
  }
  let body: EditBody | null = null
  if (!invalid && view === 'dossier') {
    if (raw !== null && raw !== value) body = { text: raw }
  } else if (!invalid && raw !== null && JSON.stringify(base) !== JSON.stringify(value)) {
    if (JSON.stringify(draft) !== JSON.stringify(value)) body = { ops: [{ op: 'set', path, value: draft }] }
  } else if (!invalid && ops.length) {
    body = { ops }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (readOnly || busy || saving.current || invalid) return
    if (!body) return
    saving.current = true
    setError('')
    try { await save(body) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not save your changes.') }
    finally { saving.current = false }
  }
  const rawText = Object.keys(inputs).length && !invalid ? pretty(draft) : raw ?? pretty(value)
  return <form onSubmit={submit}>
    <fieldset disabled={busy || readOnly}>
      {fields.map(field => {
        const current = currentValue(field)
        return <FieldInput key={field.path} field={field} text={inputs[field.path] ?? fieldText(current, field.kind)}
          readOnly={(isRecord && data.protected.includes(field.path)) || (isStop && raw !== null && !!invalid && !Object.keys(inputs).length)}
          change={text => { setInputs(old => ({ ...old, [field.path]: text })); setError(''); dirty() }} />
      })}
      {view === 'dossier' && <label>Dossier markdown<textarea rows={20} value={raw ?? String(value)} onChange={e => changeRaw(e.target.value)} /></label>}
      {view === 'everything' && <FieldInput field={rawField} text={rawText} change={changeRaw} />}
      {isStop && <details><summary>All fields (JSON)</summary>
        <FieldInput field={rawField} text={rawText} change={changeRaw} readOnly={!!invalid && Object.keys(inputs).length > 0} />
      </details>}
    </fieldset>
    {(invalid || error) && <p role="alert" className="lw-voyage-error">{invalid || error}</p>}
    <button className="lw-primary" disabled={busy || readOnly || !body}>{busy ? 'Saving…' : 'Save'}</button>
  </form>
}
