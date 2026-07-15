import { useRef, useEffect } from 'react'
import type { Message } from '../../types'
import { MessageBubble } from './MessageBubble'
import './MessageList.css'

interface MessageListProps {
  messages: Message[]
  currentUserId: string | null
  onFork?: (messageId: string) => void
  onReply?: (messageId: string) => void
  streamingMessageId?: string | null
  userNames?: Record<string, string>
}

function getAuthorName(msg: Message, userNames: Record<string, string>): string {
  if (msg.speaker_type === 'llm_primary') return 'Claude'
  if (msg.speaker_type === 'llm_provoker') return 'Claude (Provoker)'
  if (msg.speaker_type === 'llm_annotator') return 'Claude (Annotator)'
  if (msg.speaker_type === 'system') return 'System'
  if (msg.user_name) return msg.user_name
  return (msg.user_id && userNames[msg.user_id]) || msg.user_id?.slice(0, 8) || 'Human'
}

function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

interface DayGroup {
  key: string
  label: string
  messages: Message[]
}

function groupByDay(messages: Message[]): DayGroup[] {
  const groups: DayGroup[] = []
  for (const msg of messages) {
    const key = new Date(msg.created_at).toDateString()
    const last = groups[groups.length - 1]
    if (last && last.key === key) {
      last.messages.push(msg)
    } else {
      groups.push({ key, label: dayLabel(msg.created_at), messages: [msg] })
    }
  }
  return groups
}

export function MessageList({ messages, currentUserId, onFork, onReply, streamingMessageId, userNames = {} }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  if (messages.length === 0) {
    return (
      <div className="messages-wrapper">
        <div className="messages-container">
          <div className="empty-state">
            <div className="empty-icon">&#9672;</div>
            <h3>Start the dialogue</h3>
            <p>Type a message to begin. Claude will join the conversation.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="messages-wrapper">
      <div className="messages-container">
        {groupByDay(messages).map(group => (
          // WHY day-group wrapper: position:sticky is constrained to the
          // parent, so the divider must share a container with its day's
          // messages to stay pinned while they scroll.
          <div className="day-group" key={group.key}>
            <div className="day-divider">
              <span className="day-divider-line" />
              <span className="day-divider-text">{group.label}</span>
              <span className="day-divider-line" />
            </div>
            {group.messages.map(msg => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isSelf={msg.user_id === currentUserId}
                authorName={getAuthorName(msg, userNames)}
                onFork={onFork}
                onReply={onReply}
                isStreaming={msg.id === streamingMessageId}
              />
            ))}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
