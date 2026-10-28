import { useState } from 'react'
import { longwayPath, longwayRequest, notifyLongwayChanged } from './api'
import { dispatchQuestion } from './record'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Reaction } from '../../types'
import type { DispatchMetadata } from './types'

const REACTIONS = [['👍', "I'd go"], ['🚫', 'Not for me'], ['❓', 'Tell me more']] as const
export function DispatchCard({ roomId, messageId, content, dispatch, reactions, currentUserId, onToggleReaction }: {
  roomId: string; messageId: string; content: string; dispatch: DispatchMetadata; reactions: Reaction[]; currentUserId?: string | null
  onToggleReaction?: (messageId: string, emoji: string, mine: boolean) => void
}) {
  const [questionError, setQuestionError] = useState('')
  const [posting, setPosting] = useState(false)
  async function ask() {
    setPosting(true); setQuestionError('')
    try {
      const text = dispatchQuestion(content)
      if (!text) throw new Error('The dispatch has no question to send.')
      await longwayRequest(longwayPath(roomId, 'questions'), {
        method: 'POST', body: JSON.stringify({ source: 'reaction', text, source_message_id: messageId, ...(dispatch.journey ? { journey: dispatch.journey } : {}) }),
      })
      notifyLongwayChanged(roomId)
    } catch (err) { setQuestionError(err instanceof Error ? err.message : 'Could not send the question') }
    finally { setPosting(false) }
  }
  return <section className="longway-dispatch" aria-label={`Dispatch · ${dispatch.week_of}`}>
    <p className="longway-dispatch-date">This week · {dispatch.week_of}</p>
    <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(content, { async: false })) }} />
    <div className="longway-actions">{REACTIONS.map(([emoji, label]) => {
      const mine = Boolean(currentUserId && reactions.find(r => r.emoji === emoji)?.user_ids.includes(currentUserId))
      return <button key={emoji} type="button" aria-pressed={mine} disabled={!onToggleReaction || (emoji === '❓' && (posting || !roomId))} onClick={() => {
        onToggleReaction?.(messageId, emoji, mine)
        if (emoji === '❓' && !mine) void ask()
        if (emoji === '❓' && mine) setQuestionError('')
      }}>{emoji} {label}</button>
    })}</div>
    {questionError && <p role="alert">{questionError} <button disabled={posting} onClick={() => void ask()}>Retry question</button></p>}
  </section>
}
