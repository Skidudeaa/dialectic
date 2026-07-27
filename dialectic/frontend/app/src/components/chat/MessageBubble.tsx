import { useEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Message, Reaction } from '../../types'
import './MessageBubble.css'

/** Small, deliberately boring set — a picker is more chrome than this needs. */
const QUICK_REACTIONS = ['👍', '🤔', '🔥', '❓', '💯']

interface MessageBubbleProps {
  message: Message
  isSelf: boolean
  authorName: string
  onFork?: (messageId: string) => void
  onReply?: (messageId: string) => void
  isStreaming?: boolean
  replyToAuthor?: string
  replyToContent?: string
  replyToMissing?: boolean
  reactions?: Reaction[]
  currentUserId?: string | null
  onToggleReaction?: (messageId: string, emoji: string, isOn: boolean) => void
  onEdit?: (messageId: string, content: string) => void
  onDelete?: (messageId: string) => void
}

/** Quoted parents are a glance, not a re-read. */
const QUOTE_MAX_CHARS = 140

function quoteExcerpt(content: string): string {
  // Markdown syntax reads as noise at quote size; flatten it to plain text.
  const flat = content
    .replace(/```[\s\S]*?```/g, '[code]')
    .replace(/[*_`>#]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return flat.length > QUOTE_MAX_CHARS ? `${flat.slice(0, QUOTE_MAX_CHARS)}…` : flat
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

export function MessageBubble({
  message,
  isSelf,
  authorName,
  onFork,
  onReply,
  isStreaming,
  replyToAuthor,
  replyToContent,
  replyToMissing,
  reactions = [],
  currentUserId,
  onToggleReaction,
  onEdit,
  onDelete,
}: MessageBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const [showPicker, setShowPicker] = useState(false)
  const editRef = useRef<HTMLTextAreaElement>(null)

  const html = useMemo(() => {
    const raw = marked.parse(message.content, { async: false }) as string
    return DOMPurify.sanitize(raw)
  }, [message.content])

  useEffect(() => {
    if (!isEditing) return
    const el = editRef.current
    if (!el) return
    el.focus()
    // Caret at the end — you almost always want to append or fix a tail, not
    // overwrite from the start.
    el.setSelectionRange(el.value.length, el.value.length)
  }, [isEditing])

  const beginEdit = () => {
    setDraft(message.content)
    setIsEditing(true)
  }

  const commitEdit = () => {
    const trimmed = draft.trim()
    // An empty edit is a delete, and should be asked for as one.
    if (!trimmed || trimmed === message.content) {
      setIsEditing(false)
      return
    }
    onEdit?.(message.id, trimmed)
    setIsEditing(false)
  }

  const cls = speakerClass(message.speaker_type, isSelf)
  const streamCls = isStreaming ? (message.speaker_type === 'llm_provoker' ? ' streaming provoker-stream' : ' streaming') : ''
  // Only your own words, and only real persisted ones — the streaming
  // placeholder has no row to revise.
  const canRevise = isSelf && !isStreaming && message.speaker_type === 'human'

  return (
    <div className={`msg ${cls}${streamCls}`} data-message-id={message.id}>
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
          {message.edited_at && <span className="msg-edited" title="This message was edited">edited</span>}
        </div>
        <div className="msg-bubble">
          {replyToContent !== undefined && (
            <div className="msg-quote">
              <span className="msg-quote-author">{replyToAuthor}</span>
              <span className="msg-quote-text">{quoteExcerpt(replyToContent)}</span>
            </div>
          )}
          {replyToMissing && (
            <div className="msg-quote msg-quote-missing">
              <span className="msg-quote-text">Replying to an earlier message</span>
            </div>
          )}
          {isEditing ? (
            <div className="msg-edit">
              <textarea
                ref={editRef}
                className="msg-edit-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') { e.preventDefault(); setIsEditing(false) }
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    commitEdit()
                  }
                }}
                rows={Math.min(8, draft.split('\n').length + 1)}
              />
              <div className="msg-edit-actions">
                <button className="msg-action-btn primary" onClick={commitEdit}>Save</button>
                <button className="msg-action-btn" onClick={() => setIsEditing(false)}>Cancel</button>
                <span className="msg-edit-hint">Enter saves &middot; Esc cancels</span>
              </div>
            </div>
          ) : (
            <div className="msg-content" dangerouslySetInnerHTML={{ __html: html }} />
          )}
        </div>

        {reactions.length > 0 && (
          <div className="msg-reactions">
            {reactions.map((reaction) => {
              const mine = Boolean(currentUserId && reaction.user_ids.includes(currentUserId))
              return (
                <button
                  key={reaction.emoji}
                  className={`reaction-pill ${mine ? 'mine' : ''}`}
                  title={reaction.user_names.join(', ')}
                  onClick={() => onToggleReaction?.(message.id, reaction.emoji, mine)}
                >
                  <span className="reaction-emoji">{reaction.emoji}</span>
                  <span className="reaction-count">{reaction.user_ids.length}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      <div className="msg-actions">
        {onToggleReaction && !isStreaming && (
          <div className="msg-react-wrap">
            <button
              className="msg-action-btn"
              onClick={() => setShowPicker((open) => !open)}
              aria-expanded={showPicker}
            >
              React
            </button>
            {showPicker && (
              <div className="reaction-picker">
                {QUICK_REACTIONS.map((emoji) => {
                  const existing = reactions.find((r) => r.emoji === emoji)
                  const mine = Boolean(currentUserId && existing?.user_ids.includes(currentUserId))
                  return (
                    <button
                      key={emoji}
                      className={`reaction-choice ${mine ? 'mine' : ''}`}
                      onClick={() => {
                        onToggleReaction(message.id, emoji, mine)
                        setShowPicker(false)
                      }}
                    >
                      {emoji}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}
        {onReply && !isStreaming && <button className="msg-action-btn" onClick={() => onReply(message.id)}>Reply</button>}
        {onFork && <button className="msg-action-btn" onClick={() => onFork(message.id)}>Fork</button>}
        {canRevise && onEdit && !isEditing && (
          <button className="msg-action-btn" onClick={beginEdit}>Edit</button>
        )}
        {canRevise && onDelete && (
          <button
            className="msg-action-btn danger"
            onClick={() => {
              if (window.confirm('Delete this message? The other person will see it disappear.')) {
                onDelete(message.id)
              }
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
