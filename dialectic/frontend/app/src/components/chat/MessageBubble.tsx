import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Message } from '../../types'
import './MessageBubble.css'

interface MessageBubbleProps {
  message: Message
  isSelf: boolean
  authorName: string
  onFork?: (messageId: string) => void
  onReply?: (messageId: string) => void
  isStreaming?: boolean
}

function speakerClass(type: Message['speaker_type'], isSelf: boolean): string {
  if (type === 'human') return isSelf ? 'msg-human-self' : 'msg-human-other'
  if (type === 'llm_primary') return 'msg-claude'
  if (type === 'llm_provoker') return 'msg-provoker'
  if (type === 'llm_annotator') return 'msg-annotator'
  return 'msg-system'
}

function avatarClass(type: Message['speaker_type'], isSelf: boolean): string {
  if (type === 'human') return isSelf ? 'avatar-self' : 'avatar-human-2'
  if (type === 'llm_primary' || type === 'llm_annotator') return 'avatar-claude'
  if (type === 'llm_provoker') return 'avatar-provoker'
  return ''
}

function avatarLabel(type: Message['speaker_type'], authorName: string): string {
  if (type === 'llm_primary') return 'C'
  if (type === 'llm_provoker') return '!'
  if (type === 'llm_annotator') return 'A'
  if (type === 'system') return '*'
  return authorName.charAt(0).toUpperCase()
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

export function MessageBubble({ message, isSelf, authorName, onFork, onReply, isStreaming }: MessageBubbleProps) {
  const html = useMemo(() => {
    const raw = marked.parse(message.content, { async: false }) as string
    return DOMPurify.sanitize(raw)
  }, [message.content])

  const cls = speakerClass(message.speaker_type, isSelf)
  const streamCls = isStreaming ? (message.speaker_type === 'llm_provoker' ? ' streaming provoker-stream' : ' streaming') : ''

  return (
    <div className={`msg ${cls}${streamCls}`}>
      {message.speaker_type !== 'system' && (
        <div className="msg-avatar">
          <div className={`avatar ${avatarClass(message.speaker_type, isSelf)}`}>
            {avatarLabel(message.speaker_type, authorName)}
          </div>
        </div>
      )}
      <div className="msg-body">
        <div className="msg-meta">
          <span className="msg-author">{authorName}</span>
          <span className="msg-time">{formatTime(message.created_at)}</span>
          {message.message_type !== 'text' && (
            <span className="msg-type-badge">{message.message_type}</span>
          )}
        </div>
        <div className="msg-bubble">
          <div className="msg-content" dangerouslySetInnerHTML={{ __html: html }} />
        </div>
      </div>
      <div className="msg-actions">
        {onReply && <button className="msg-action-btn" onClick={() => onReply(message.id)}>Reply</button>}
        {onFork && <button className="msg-action-btn" onClick={() => onFork(message.id)}>Fork</button>}
      </div>
    </div>
  )
}
