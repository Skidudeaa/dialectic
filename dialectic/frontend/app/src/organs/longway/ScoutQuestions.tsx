import { useEffect, useRef, useState } from 'react'
import { useLongwayQuestions } from '../../hooks/useLongwayQuestions'
import { useLongwayScoutRuns } from '../../hooks/useLongwayScoutRuns'
import { longwayPath, longwayRequest, notifyLongwayChanged } from './api'

export function ScoutQuestions({ roomId, canManageHome }: { roomId: string; canManageHome: boolean }) {
  const questions = useLongwayQuestions(roomId)
  const runs = useLongwayScoutRuns(roomId)
  const [text, setText] = useState('')
  const [asking, setAsking] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startedRun, setStartedRun] = useState<string | null>(null)
  const [questionError, setQuestionError] = useState('')
  const [runError, setRunError] = useState('')
  const [asked, setAsked] = useState(false)
  const completed = useRef<string | null>(null)
  const latest = runs.data?.[0]
  const running = runs.data?.some(run => run.status === 'running') || Boolean(startedRun && !runs.data?.some(run => run.id === startedRun && run.status !== 'running'))
  useEffect(() => {
    if (latest && latest.status !== 'running' && completed.current !== latest.id) {
      completed.current = latest.id
      notifyLongwayChanged(roomId)
    }
  }, [latest, roomId])
  async function ask() {
    if (asking || !text.trim()) return
    setAsking(true); setQuestionError(''); setAsked(false)
    try {
      await longwayRequest(longwayPath(roomId, 'questions'), { method: 'POST', body: JSON.stringify({ text: text.trim(), source: 'human' }) })
      setText(''); setAsked(true); questions.refresh()
    } catch (err) { setQuestionError(err instanceof Error ? err.message : 'Could not ask the Scout') }
    finally { setAsking(false) }
  }
  async function scout() {
    if (starting || running) return
    setStarting(true); setRunError('')
    try {
      const result = await longwayRequest<{ run_id: string }>(longwayPath(roomId, 'scout'), { method: 'POST', body: '{}' })
      setStartedRun(result.run_id); runs.refresh()
    } catch (err) { setRunError(err instanceof Error ? err.message : 'Could not start the Scout'); runs.refresh() }
    finally { setStarting(false) }
  }
  return <section className="longway-scout" aria-label="What the Scout is working on">
    <h2>What the Scout is working on</h2>
    {questions.error && <p role="alert">{questions.error} <button onClick={questions.refresh}>Retry questions</button></p>}
    {!questions.data && !questions.error && <p role="status">Loading questions…</p>}
    {questions.data && (questions.data.filter(q => !q.closed_at).length ? <ul className="longway-questions">{questions.data.filter(q => !q.closed_at).map(q => <li key={q.id}><span>{q.text}</span> <small>{q.source}</small>{q.answer_review && <small> · {q.answer_review === 'proposed' ? 'answered below, awaiting confirmation' : `answer ${q.answer_review}`}</small>}</li>)}</ul> : <p>No open questions yet.</p>)}
    <form onSubmit={e => { e.preventDefault(); void ask() }}><label>Ask the Scout to find out<input required value={text} onChange={e => { setText(e.target.value); setAsked(false) }} /></label><button disabled={asking || !text.trim()}>{asking ? 'Asking…' : 'Ask the Scout'}</button></form>
    {questionError && <p role="alert">{questionError}</p>}{asked && <p role="status">Question sent to the Scout.</p>}
    {canManageHome && <button type="button" disabled={starting || running || !runs.data || Boolean(runs.error)} onClick={() => void scout()}>Scout this</button>}
    {(starting || running) && <p role="status">Scout running…</p>}
    {latest && <p className="longway-scout-receipt">Scout {latest.status === 'running' ? 'so far: ' : ''}read {latest.pages_read} pages, filed {latest.proposals} proposals, {latest.counter_proposals} contrary findings{latest.status === 'failed' || latest.status === 'killed' ? ` · ${latest.status}${latest.error ? `: ${latest.error}` : ''}` : ''}</p>}
    {runs.error && <p role="alert">{runs.error} <button onClick={runs.refresh}>Retry Scout runs</button></p>}
    {runError && <p role="alert">{runError}</p>}
  </section>
}
