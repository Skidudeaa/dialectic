import { useState, useRef, useCallback, type KeyboardEvent } from 'react'
import type { Message } from '../../types'
import './MessageInput.css'

type MessageType = Message['message_type']

interface MessageInputProps {
  onSend: (content: string, messageType: MessageType) => void
  onTypingStart?: () => void
  onTypingStop?: () => void
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

export function MessageInput({ onSend, onTypingStart, onTypingStop, disabled, replyTo, onCancelReply }: MessageInputProps) {
  const [content, setContent] = useState('')
  const [messageType, setMessageType] = useState<MessageType>('text')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const typingRef = useRef(false)

  const handleSend = useCallback(() => {
    const trimmed = content.trim()
    if (!trimmed) return
    onSend(trimmed, messageType)
    setContent('')
    setMessageType('text')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    onTypingStop?.()
    typingRef.current = false
  }, [content, messageType, onSend, onTypingStop])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = (value: string) => {
    setContent(value)
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
          <button className="send-btn" onClick={handleSend} disabled={disabled || !content.trim()} title="Send (Cmd+Enter)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
        <div className="input-hints">
          <span>Shift+Enter for newline</span>
          <span>? for shortcuts</span>
        </div>
      </div>
    </div>
  )
}
