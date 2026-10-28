import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Reaction } from '../../types'
import type { DispatchMetadata } from './types'

const REACTIONS = [['👍', "I'd go"], ['🚫', 'Not for me'], ['❓', 'Tell me more']] as const
export function DispatchCard({ messageId, content, dispatch, reactions, currentUserId, onToggleReaction }: {
  messageId: string; content: string; dispatch: DispatchMetadata; reactions: Reaction[]; currentUserId?: string | null
  onToggleReaction?: (messageId: string, emoji: string, mine: boolean) => void
}) {
  return <section className="longway-dispatch" aria-label={`Dispatch · ${dispatch.week_of}`}>
    <p className="longway-dispatch-date">This week · {dispatch.week_of}</p>
    <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(content, { async: false })) }} />
    <div className="longway-actions">{REACTIONS.map(([emoji, label]) => {
      const mine = Boolean(currentUserId && reactions.find(r => r.emoji === emoji)?.user_ids.includes(currentUserId))
      return <button key={emoji} type="button" aria-pressed={mine} disabled={!onToggleReaction} onClick={() => onToggleReaction?.(messageId, emoji, mine)}>{emoji} {label}</button>
    })}</div>
  </section>
}
