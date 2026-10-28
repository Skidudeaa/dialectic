import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import { useLongwayChart } from '../../hooks/useLongwayChart'
import { longwayPath, longwayRequest } from './api'
import Chart from './chartSlot'

export function LongwayHouse({ roomId, canManageHome, onNavigate }: {
  roomId: string; canManageHome: boolean; onNavigate: (roomId: string) => Promise<unknown> | void
}) {
  const { data, error, refresh } = useLongwayChart(roomId)
  const [selected, setSelected] = useState<string | null>(null)
  const [myth, setMyth] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [writeError, setWriteError] = useState('')
  // Retain a created room if bind fails: retry binds that room, never creates
  // another one. The created id is exposed with the failure for recovery.
  const created = useRef<Record<string, { id: string; token: string }>>({})
  const opening = useRef(false)
  async function openRoom(slug: string, title: string) {
    if (opening.current || !canManageHome) return
    opening.current = true; setBusy(slug); setWriteError('')
    try {
      const room = created.current[slug] ?? await api.createRoom(title) as { id: string; token: string }
      created.current[slug] = room
      await longwayRequest(longwayPath(room.id, 'bind'), { method: 'POST', body: JSON.stringify({ slug }) }, room.token)
      refresh()
      if (await onNavigate(room.id) === false) throw new Error('Room is ready but could not be entered')
    } catch (error) {
      setWriteError(`${error instanceof Error ? error.message : 'Could not open room'}${created.current[slug] ? ` — room ${created.current[slug].id} exists; retry to finish opening it.` : ''}`)
    } finally { opening.current = false; setBusy(null) }
  }
  if (error) return <div role="alert">{error} <button onClick={refresh}>Retry house</button></div>
  if (!data) return <p role="status">Chart loading</p>
  return <div className="longway-house scene-body">
    <div className="longway-chart"><Chart data={data} focus={null} selected={selected} myth={myth} onSelectJourney={setSelected} onSelectLeg={slug => setSelected(slug)} /></div>
    <label><input type="checkbox" checked={myth} onChange={e => setMyth(e.target.checked)} /> Without the mythology</label>
    <section aria-label="Your rooms"><h2>Your rooms</h2>{data.rooms.map(room => <p key={room.id}>
      <button onClick={() => void onNavigate(room.id)}>{room.name}</button>{room.linked_journey && ` · ${data.journeys.find(j => j.slug === room.linked_journey)?.title ?? room.linked_journey}`}
    </p>)}</section>
    {writeError && <p role="alert">{writeError}</p>}
    <section aria-label="Journeys"><h2>Journeys</h2>{data.journeys.map(journey => {
      const room = data.rooms.find(r => r.linked_journey === journey.slug)
      return <article key={journey.slug} className="longway-card" data-selected={selected === journey.slug || undefined}>
        <h3><button onClick={() => setSelected(journey.slug)}>{journey.title}</button></h3>
        <p>{journey.pull}</p><p>{journey.status} · {journey.feasibility ?? 'unknown'}</p>
        {room ? <button onClick={() => void onNavigate(room.id)}>Open {room.name}</button>
          : canManageHome && journey.kind === 'candidate' && <button disabled={busy !== null} onClick={() => void openRoom(journey.slug, journey.title)}>{busy === journey.slug ? 'Opening…' : 'Open a room for this journey'}</button>}
      </article>
    })}</section>
  </div>
}
