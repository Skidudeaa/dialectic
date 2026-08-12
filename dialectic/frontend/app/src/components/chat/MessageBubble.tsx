import { useEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Attachment, Message, Reaction } from '../../types'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { MessageAttachments } from './MessageAttachments'
import './MessageBubble.css'

/** Small, deliberately boring set — a picker is more chrome than this needs. */
const QUICK_REACTIONS = ['👍', '🤔', '🔥', '❓', '💯']

/**
 * Above this many characters a message is folded behind "Show more".
 *
 * WHY a character count rather than measuring rendered height: measuring means
 * writing state from an effect after layout, which cascades renders on every
 * streamed token. The threshold only has to be approximately right — it decides
 * whether to offer the fold, and the reader decides the rest.
 */
const FOLD_THRESHOLD_CHARS = 700

/**
 * Annotations are notes left for whoever was offline, not turns in the
 * conversation, so they start folded however long they are. Left expanded they
 * routinely filled the whole viewport and buried what the humans actually said.
 */
const ALWAYS_FOLDED: ReadonlySet<string> = new Set(['llm_annotator'])

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
  /** Same speaker continuing — avatar and byline are suppressed as repetition. */
  isContinuation?: boolean
  /** Media carried by this message, if any. */
  attachments?: Attachment[]
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
  isContinuation,
  attachments = [],
}: MessageBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const [showPicker, setShowPicker] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [acceptState, setAcceptState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const editRef = useRef<HTMLTextAreaElement>(null)
  const currentRoomId = useAppStore((s) => s.currentRoom?.id)

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

  // A message still arriving is never folded — watching it write itself is the
  // point, and a fold appearing mid-stream would be jarring.
  const foldable = !isStreaming && !isEditing && (
    ALWAYS_FOLDED.has(message.speaker_type) || message.content.length > FOLD_THRESHOLD_CHARS
  )
  const isFolded = foldable && !isExpanded

  // Which live checks this answer rests on. Collapsed by default for the same
  // reason annotations are: it is provenance, available when someone doubts a
  // number, not something to read on every turn.
  const toolCalls = message.metadata?.tools?.calls ?? []

  // A drafted prediction, if this turn made one. The Accept tap is the ONLY
  // write — the tool itself logged nothing. Local state carries the accepted
  // flip; on reload the server-stamped flag does.
  const proposal = message.metadata?.proposal
  const proposalLogged = Boolean(proposal?.accepted) || acceptState === 'accepted'

  // A proposed thesis, if this turn made one. Nothing exists yet — the tap
  // seeds the Create Thesis form and opens the Trading tab, where the
  // cascade is drafted and reviewed before anything is created.
  const thesisProposal = message.metadata?.thesis_proposal
  const openThesisCreate = () => {
    if (!thesisProposal) return
    const state = useAppStore.getState()
    state.setThesisSeed({
      title: thesisProposal.title,
      claim: thesisProposal.claim,
      monthlyBudget: thesisProposal.monthly_budget ?? 5000,
    })
    state.setRightPanelTab('trading')
    // On a phone the panel is a drawer — opening the tab without opening
    // the drawer would make this tap a silent no-op.
    state.setMobileDrawer('panel')
  }

  const acceptProposal = async () => {
    if (!currentRoomId || acceptState === 'accepting' || proposalLogged) return
    setAcceptState('accepting')
    try {
      await api.acceptPrediction(currentRoomId, message.id)
      setAcceptState('accepted')
    } catch {
      setAcceptState('error')
    }
  }

  return (
    <div
      className={`msg ${cls}${streamCls}${isContinuation ? ' msg-continuation' : ''}`}
      data-message-id={message.id}
    >
      {message.speaker_type !== 'system' && (
        <div className="msg-avatar">
          {/* The slot is kept even when the avatar is suppressed, so grouped
              messages stay aligned with the one that carries the byline. */}
          {!isContinuation && (
            <div className={`avatar ${avatarClass(message.speaker_type, isSelf)}`}>
              {avatarLabel(message.speaker_type, authorName)}
            </div>
          )}
        </div>
      )}
      <div className="msg-body">
        {!isContinuation && (
          <div className="msg-meta">
            <span className="msg-author">{authorName}</span>
            <span className="msg-time">{formatTime(message.created_at)}</span>
            {message.message_type !== 'text' && (
              <span className="msg-type-badge">{message.message_type}</span>
            )}
            {message.edited_at && <span className="msg-edited" title="This message was edited">edited</span>}
          </div>
        )}
        <div className={`msg-bubble${isFolded ? ' msg-folded' : ''}`}>
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
          {isFolded && <div className="msg-fold-veil" aria-hidden="true" />}
        </div>

        {foldable && (
          <button
            className="msg-fold-toggle"
            onClick={() => setIsExpanded((open) => !open)}
            aria-expanded={isExpanded}
          >
            {isExpanded ? 'Show less' : 'Show more'}
          </button>
        )}
        {/* Outside the bubble, so a folded message still shows what it carried —
            the picture is usually the point of the message, not its tail. */}
        {attachments.length > 0 && <MessageAttachments attachments={attachments} />}

        {toolCalls.length > 0 && (
          <div className="msg-tools">
            <button
              className="msg-tools-toggle"
              onClick={() => setShowTools((open) => !open)}
              aria-expanded={showTools}
            >
              · used {toolCalls.length} tool{toolCalls.length === 1 ? '' : 's'}
            </button>
            {showTools && (
              <ul className="msg-tools-list">
                {toolCalls.map((call, index) => (
                  <li
                    key={`${call.name}-${index}`}
                    className={call.ok ? 'msg-tool-ok' : 'msg-tool-failed'}
                  >
                    <span className="msg-tool-name">{call.name}</span>
                    {call.label && <span className="msg-tool-label">— {call.label}</span>}
                    {typeof call.latency_ms === 'number' && (
                      <span className="msg-tool-latency">— {call.latency_ms}ms</span>
                    )}
                    {call.provenance && Object.keys(call.provenance).length > 0 && (
                      <span className="msg-tool-provenance">
                        — {Object.entries(call.provenance)
                          .map(([key, value]) => `${key}: ${String(value)}`)
                          .join(', ')}
                      </span>
                    )}
                    {call.error && <span className="msg-tool-error">— {call.error}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {proposal && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">Drafted prediction</div>
            <div className="msg-proposal-statement">{proposal.statement}</div>
            <div className="msg-proposal-meta">
              {Math.round(proposal.confidence * 100)}% by {proposal.deadline}
              {proposal.linked_book_id && ` · ${proposal.linked_book_id}`}
            </div>
            {proposalLogged ? (
              <span className="msg-proposal-logged">logged to tradingDesk</span>
            ) : (
              <button
                className="msg-proposal-accept"
                disabled={acceptState === 'accepting'}
                onClick={acceptProposal}
              >
                {acceptState === 'accepting' ? 'Logging…' : 'Accept'}
              </button>
            )}
            {acceptState === 'error' && !proposalLogged && (
              <span className="msg-proposal-error">could not log — try again</span>
            )}
          </div>
        )}

        {thesisProposal && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">Proposed thesis</div>
            <div className="msg-proposal-statement">{thesisProposal.title}</div>
            <div className="msg-proposal-meta">{thesisProposal.claim}</div>
            <div className="msg-proposal-meta">
              ${(thesisProposal.monthly_budget ?? 5000).toLocaleString()}/mo
              · nothing exists until you review the draft
            </div>
            <button className="msg-proposal-accept" onClick={openThesisCreate}>
              Draft the cascade →
            </button>
          </div>
        )}

        {/* The byline is suppressed on grouped messages, so an edit made to one
            would otherwise be invisible. */}
        {isContinuation && message.edited_at && (
          <span className="msg-edited msg-edited-standalone">edited</span>
        )}

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
