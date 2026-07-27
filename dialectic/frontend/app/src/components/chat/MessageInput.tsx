import { useState, useRef, useCallback, type KeyboardEvent } from 'react'
import type { Message } from '../../types'
import './MessageInput.css'

type MessageType = Message['message_type']

interface MessageInputProps {
  onSend: (content: string, messageType: MessageType) => boolean
  onTypingStart?: () => void
  onTypingStop?: () => void
  onTypingContent?: (content: string) => void
  disabled?: boolean
  replyTo?: { author: string; content: string } | null
  onCancelReply?: () => void
}

const MESSAGE_TYPES: { value: MessageType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'claim', label: 'Claim' },
  { value: 'question', label: 'Question' },
  { value: 'definition', label: 'Definition' },
]

export function MessageInput({ onSend, onTypingStart, onTypingStop, onTypingContent, disabled, replyTo, onCancelReply }: MessageInputProps) {
  const [content, setContent] = useState('')
  const [messageType, setMessageType] = useState<MessageType>('text')
  const [sendError, setSendError] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const typingRef = useRef(false)

  const handleSend = useCallback(() => {
    const trimmed = content.trim()
    if (!trimmed) return
    const sent = onSend(trimmed, messageType)
    // WHY: onSend returns false when the socket is not open. This used to be a
    // silent no-op — the text stayed in the box with no indication it had not
    // been delivered, which reads as "the app ate my message."
    if (!sent) {
      setSendError(true)
      return
    }
    setSendError(false)
    setContent('')
    setMessageType('text')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    onTypingStop?.()
    typingRef.current = false
  }, [content, messageType, onSend, onTypingStop])

  // Enter sends, Shift+Enter inserts a newline — the convention the hint text
  // has always claimed. Cmd/Ctrl+Enter stays supported for muscle memory.
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter') return
    if (e.shiftKey) return
    // A composing IME uses Enter to accept a candidate; sending there would cut
    // the word off mid-entry.
    if (e.nativeEvent.isComposing) return
    e.preventDefault()
    handleSend()
  }

  const handleInput = (value: string) => {
    setContent(value)
    onTypingContent?.(value)
    // Auto-resize
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
    }
    // Typing indicators
    if (value && !typingRef.current) {
      typingRef.current = true
      onTypingStart?.()
    } else if (!value && typingRef.current) {
      typingRef.current = false
      onTypingStop?.()
    }
  }

  return (
    <div className="input-area">
      <div className="input-area-inner">
        {replyTo && (
          <div className="reply-preview-bar active">
            <div className="reply-preview-text">
              <strong>{replyTo.author}</strong>
              <span>{replyTo.content}</span>
            </div>
            <button className="cancel-reply" onClick={onCancelReply}>&times;</button>
          </div>
        )}
        <div className="msg-type-selector">
          {MESSAGE_TYPES.map(t => (
            <button
              key={t.value}
              className={`type-btn ${messageType === t.value ? 'active' : ''}`}
              onClick={() => setMessageType(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="input-row">
          <textarea
            ref={textareaRef}
            className="msg-textarea"
            placeholder="Think out loud... (use @llm to summon Claude)"
            rows={1}
            value={content}
            onChange={e => handleInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
          />
          <button className="send-btn" onClick={handleSend} disabled={disabled || !content.trim()} title="Send (Enter)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
        <div className="input-hints">
          {sendError ? (
            <span className="input-error" role="alert">
              Not connected — your message wasn&rsquo;t sent. It&rsquo;s still here; try again once you reconnect.
            </span>
          ) : (
            <span>Enter to send &middot; Shift+Enter for newline</span>
          )}
          <span>? for shortcuts</span>
        </div>
      </div>
    </div>
  )
}
