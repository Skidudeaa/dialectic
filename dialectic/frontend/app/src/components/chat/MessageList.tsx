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
}

function getAuthorName(msg: Message): string {
  if (msg.speaker_type === 'llm_primary') return 'Claude'
  if (msg.speaker_type === 'llm_provoker') return 'Claude (Provoker)'
  if (msg.speaker_type === 'llm_annotator') return 'Claude (Annotator)'
  if (msg.speaker_type === 'system') return 'System'
  return msg.user_id?.slice(0, 8) ?? 'Human'
}

export function MessageList({ messages, currentUserId, onFork, onReply, streamingMessageId }: MessageListProps) {
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
        {messages.map(msg => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isSelf={msg.user_id === currentUserId}
            authorName={getAuthorName(msg)}
            onFork={onFork}
            onReply={onReply}
            isStreaming={msg.id === streamingMessageId}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
