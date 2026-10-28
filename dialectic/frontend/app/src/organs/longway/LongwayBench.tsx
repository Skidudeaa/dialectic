import { useState } from 'react'
import type { ReactNode } from 'react'
import { useLongwayChart } from '../../hooks/useLongwayChart'
import { useAppStore } from '../../stores/appStore'
import Chart, { LegCard, SeasonStrip } from './chartSlot'
import { longwayPath, longwayRequest } from './api'
import type { AnchorMetadata } from './types'

export function LongwayBench({ roomId, record, canManageHome = false }: { roomId: string; record?: ReactNode; canManageHome?: boolean }) {
  const { data, error, refresh } = useLongwayChart(roomId)
  const [selected, setSelected] = useState<string | null>(null)
  const [leg, setLeg] = useState<AnchorMetadata | null>(null)
  const [myth, setMyth] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const [sendError, setSendError] = useState('')
  // The Sunday ritual's manual door (house managers): same draft, post and push as the job, once per day.
  const [dispatchNote, setDispatchNote] = useState('')
  const [dispatching, setDispatching] = useState(false)
  const sendDispatch = async () => {
    setDispatching(true); setDispatchNote('')
    try {
      const result = await longwayRequest<{ message_id: string | null; pushed: number; already: boolean }>(longwayPath(roomId, 'dispatch/now'), { method: 'POST' })
      setDispatchNote(result.already ? 'This week’s dispatch was already sent today; it is in the Record.' : 'Sent to the Record and pushed.')
    } catch (err) {
      setDispatchNote(err instanceof Error ? err.message : 'The dispatch could not be sent.')
    } finally {
      setDispatching(false)
    }
  }
  const journey = data?.journeys.find(j => j.slug === (leg?.journey ?? selected ?? data.room.linked_journey))
  const discuss = (slug: string, index: number) => {
    const segment = data?.journeys.find(j => j.slug === slug)?.segments[index]
    if (!segment) return
    setLeg({ journey: slug, leg: index })
    setDraft(`About ${segment.from} to ${segment.to}:`)
    setSendError('')
  }
  if (error) return <div role="alert">{error} <button onClick={refresh}>Retry chart</button></div>
  if (!data) return <p role="status">Chart loading</p>
  return <div className="longway-bench">
    <div className="longway-chart"><Chart data={data} focus={data.room.linked_journey} selected={selected ?? data.room.linked_journey} myth={myth}
      onSelectJourney={slug => { setSelected(slug); setLeg(null); setDraft(null) }}
      onSelectLeg={(slug, index) => { setSelected(slug); setLeg({ journey: slug, leg: index }); setDraft(null) }} onDiscussLeg={discuss} /></div>
    <div className="longway-chart-notes">
      <label><input type="checkbox" checked={myth} onChange={e => setMyth(e.target.checked)} /> Without the mythology</label>
      {journey && <><h3>{journey.title}</h3><p>{journey.pull}</p><SeasonStrip season={journey.season} sources={data.sources[journey.slug] ?? {}} />
        <ul className="longway-legs">{journey.segments.map((segment, index) => <li key={index}><button aria-pressed={leg?.journey === journey.slug && leg.leg === index} onClick={() => { setLeg({ journey: journey.slug, leg: index }); setDraft(null) }}>{segment.from} to {segment.to}</button></li>)}</ul>
      </>}
      {journey && leg && <><LegCard journey={journey} index={leg.leg} sources={data.sources[journey.slug] ?? {}} />
        <button onClick={() => discuss(journey.slug, leg.leg)}>Discuss this leg</button></>}
      {draft !== null && <form onSubmit={e => {
        e.preventDefault()
        const { wsSend, currentThread, currentRoom } = useAppStore.getState()
        if (!leg || currentRoom?.id !== roomId || !currentThread || !wsSend?.('send_message', { thread_id: currentThread.id, type: 'text', content: draft, metadata: { longway_anchor: leg } })) {
          setSendError('Reconnect before sending. Your draft is still here.'); return
        }
        setDraft(null); setSendError('')
      }}><label>About this leg<textarea autoFocus value={draft} onChange={e => setDraft(e.target.value)} /></label>
        <button disabled={!draft.trim()}>Send to Record</button><button type="button" onClick={() => setDraft(null)}>Cancel</button>{sendError && <p role="alert">{sendError}</p>}
      </form>}
      {canManageHome && (data.room.linked_journey || data.room.is_home) && <p className="longway-dispatch-now">
        <button type="button" disabled={dispatching} onClick={() => void sendDispatch()}>{dispatching ? 'Sending…' : 'Send this week’s dispatch now'}</button>
        {dispatchNote && <span role="status"> {dispatchNote}</span>}
      </p>}
      {data.fixes_state.stale && <p>{data.fixes_state.why ?? 'Vehicle listener is stale'}</p>}
      {data.vehicles.filter(v => !v.heard && (!data.room.linked_journey || v.journey === data.room.linked_journey)).map(v => <p key={`${v.journey}:${v.name}`}>{v.name} · never heard</p>)}
    </div>
    {record && <div className="longway-bench-record">{record}</div>}
  </div>
}
