import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import type { Attachment, Message, Reaction } from '../../types'
import { useDocumentVisibility } from '../../hooks/useDocumentVisibility'
import { MessageBubble } from './MessageBubble'
import './MessageList.css'

interface MessageListProps {
  messages: Message[]
  currentUserId: string | null
  onFork?: (messageId: string) => void
  onReply?: (messageId: string) => void
  streamingMessageId?: string | null
  userNames?: Record<string, string>
  /**
   * Timestamp of the reader's last read receipt in this room (or their join
   * time). Everything after it that someone else wrote is new since they were
   * last here. Frozen on entry so the line does not move while they read.
   */
  unreadSince?: string | null
  /** Reports the newest message the reader has actually had in front of them. */
  onSeen?: (messageId: string) => void
  /** A message to scroll to and flash, e.g. after picking a search result. */
  jumpTarget?: { id: string; nonce: number } | null
  reactions?: Record<string, Reaction[]>
  /** Media keyed by message id; absent means the message carried none. */
  attachments?: Record<string, Attachment[]>
  onToggleReaction?: (messageId: string, emoji: string, isOn: boolean) => void
  onEditMessage?: (messageId: string, content: string) => void
  onDeleteMessage?: (messageId: string) => void
  /** Home's empty state is a table, not a prompt to start a chat. */
  emptyKind?: 'dialogue' | 'hearth'
}

/**
 * How close to the bottom counts as "following the conversation". Slightly more
 * than one line of text, so a stray trackpad nudge doesn't drop you out of
 * follow mode.
 */
const FOLLOW_THRESHOLD_PX = 120

/**
 * Consecutive messages from the same speaker within this window are shown as
 * one block, without repeating the avatar and byline. Beyond it the gap is long
 * enough that re-stating who is talking, and when, is worth the space.
 */
const GROUPING_WINDOW_MS = 5 * 60 * 1000

function continuesPrevious(current: Message, previous: Message | undefined): boolean {
  if (!previous) return false
  if (current.speaker_type !== previous.speaker_type) return false
  // Distinguishes the two humans; both are null for Claude, whose speaker_type
  // has already separated primary from provoker from annotator.
  if (current.user_id !== previous.user_id) return false
  const gap = new Date(current.created_at).getTime() - new Date(previous.created_at).getTime()
  return Number.isFinite(gap) && gap >= 0 && gap < GROUPING_WINDOW_MS
}

function getAuthorName(msg: Message, userNames: Record<string, string>): string {
  if (msg.speaker_type === 'llm_primary') return PARTICIPANT_NAME
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

export function MessageList({
  messages,
  currentUserId,
  onFork,
  onReply,
  streamingMessageId,
  userNames = {},
  unreadSince,
  onSeen,
  jumpTarget,
  reactions = {},
  attachments = {},
  onToggleReaction,
  onEditMessage,
  onDeleteMessage,
  emptyKind = 'dialogue',
}: MessageListProps) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Whether the reader is pinned to the live end of the conversation. Starts
  // true so a freshly opened thread lands at the newest message.
  //
  // WHY these are state rather than refs, and why they are only ever written
  // from event handlers: the unread count is derived during render instead of
  // accumulated inside an effect, which keeps scroll syncing free of the
  // cascading-render problem that setState-in-effect creates.
  const [isFollowing, setIsFollowing] = useState(true)
  // Message count at the moment the reader stopped following. Everything after
  // it is what they have not seen.
  const [seenCount, setSeenCount] = useState(messages.length)

  const missedCount = isFollowing ? 0 : Math.max(0, messages.length - seenCount)

  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    bottomRef.current?.scrollIntoView({ behavior, block: 'end' })
  }, [])

  const handleScroll = useCallback(() => {
    const el = wrapperRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    const following = distanceFromBottom <= FOLLOW_THRESHOLD_PX
    setIsFollowing((wasFollowing) => {
      // Leaving the tail: snapshot how much had been read, so arrivals from
      // here on are the ones counted as missed.
      if (wasFollowing && !following) setSeenCount(messages.length)
      return following
    })
  }, [messages.length])

  const handleJumpToLatest = useCallback(() => {
    setIsFollowing(true)
    scrollToBottom('smooth')
  }, [scrollToBottom])

  // WHY useLayoutEffect: run before paint so the jump to the newest message is
  // never visible as a scroll animation on first render of a thread.
  //
  // 'auto' rather than 'smooth': a smooth scroll re-queued per streamed token
  // never settles, which is what made the stream feel like it was dragging the
  // page around. When the reader is NOT following, this does nothing at all —
  // that is the whole fix for losing your place mid-history.
  useLayoutEffect(() => {
    if (isFollowing) scrollToBottom('auto')
  }, [messages, streamingMessageId, isFollowing, scrollToBottom])

  const isVisible = useDocumentVisibility()

  // The first message someone else wrote after the reader was last here. Derived
  // rather than frozen: `unreadSince` is stable for the lifetime of a room
  // session (see App), so the line does not creep down as messages are marked
  // read underneath it.
  const firstUnreadId = useMemo(() => {
    if (!unreadSince) return null
    const boundary = new Date(unreadSince).getTime()
    if (Number.isNaN(boundary)) return null
    return messages.find(
      (message) =>
        message.user_id !== currentUserId &&
        new Date(message.created_at).getTime() > boundary,
    )?.id ?? null
  }, [messages, unreadSince, currentUserId])

  // Report the newest message as read, but only when it is genuinely in front of
  // the reader: tab in the foreground AND scrolled to the live end. Marking read
  // on delivery alone is exactly what would make the badge lie.
  useEffect(() => {
    if (!onSeen || !isFollowing || !isVisible) return
    for (let i = messages.length - 1; i >= 0; i--) {
      const candidate = messages[i]
      if (candidate.id === streamingMessageId) continue
      onSeen(candidate.id)
      return
    }
  }, [messages, isFollowing, isVisible, onSeen, streamingMessageId])

  // Scroll to a jumped-to message and flash it, so the eye lands on the right
  // line in a wall of text. Pure DOM work — the flash class is added and removed
  // directly rather than held in state.
  useEffect(() => {
    if (!jumpTarget) return
    const el = wrapperRef.current?.querySelector(`[data-message-id="${CSS.escape(jumpTarget.id)}"]`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('msg-flash')
    const timer = window.setTimeout(() => el.classList.remove('msg-flash'), 1600)
    return () => {
      window.clearTimeout(timer)
      el.classList.remove('msg-flash')
    }
  }, [jumpTarget, messages])

  // Parent lookup for reply quoting. The referenced message may be outside the
  // loaded window (older than the fetched page), in which case the bubble
  // renders an unresolved-reference placeholder instead of pretending.
  const messagesById = useMemo(() => {
    const map = new Map<string, Message>()
    for (const msg of messages) map.set(msg.id, msg)
    return map
  }, [messages])

  if (messages.length === 0) {
    if (emptyKind === 'hearth') {
      return (
        <div className="messages-wrapper messages-wrapper-hearth">
          <div className="hearth-empty">
            <p className="hearth-kicker">The table</p>
            <p className="hearth-copy">Sit down when you want to talk. The house is above.</p>
          </div>
        </div>
      )
    }
    // Most rooms are empty most of the time, so this is a primary surface
    // rather than a placeholder. It has to carry the one thing a newcomer
    // cannot guess: the participant joins on its own judgment, and there is
    // also a way to address it directly.
    return (
      <div className="messages-wrapper">
        <div className="messages-container">
          <div className="empty-state">
            <div className="empty-icon">&#9672;</div>
            <h3>Start the dialogue</h3>
            <p className="empty-premise" data-testid="empty-room-premise">
              Write what you are actually chewing on. {PARTICIPANT_NAME} reads
              along and joins when it judges it has something — a challenge, a
              connection, a check against live data. Say{' '}
              <strong>@{PARTICIPANT_NAME}</strong> to bring it in directly.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="messages-viewport">
      <div className="messages-wrapper" ref={wrapperRef} onScroll={handleScroll}>
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
              {group.messages.map((msg, index) => {
                const parent = msg.references_message_id
                  ? messagesById.get(msg.references_message_id)
                  : undefined
                // The unread line is a deliberate break in the conversation, so
                // the message under it always re-states who is speaking.
                const isContinuation =
                  msg.id !== firstUnreadId
                  && continuesPrevious(msg, group.messages[index - 1])
                return (
                  <Fragment key={msg.id}>
                  {msg.id === firstUnreadId && (
                    <div className="unread-divider" role="separator">
                      <span className="unread-divider-line" />
                      <span className="unread-divider-text">New since you were last here</span>
                      <span className="unread-divider-line" />
                    </div>
                  )}
                  <MessageBubble
                    message={msg}
                    isSelf={msg.user_id === currentUserId}
                    authorName={getAuthorName(msg, userNames)}
                    onFork={onFork}
                    onReply={onReply}
                    isStreaming={msg.id === streamingMessageId}
                    replyToAuthor={parent ? getAuthorName(parent, userNames) : undefined}
                    replyToContent={parent?.content}
                    replyToMissing={Boolean(msg.references_message_id && !parent)}
                    reactions={reactions[msg.id]}
                    attachments={attachments[msg.id]}
                    currentUserId={currentUserId}
                    onToggleReaction={onToggleReaction}
                    onEdit={onEditMessage}
                    onDelete={onDeleteMessage}
                    isContinuation={isContinuation}
                  />
                  </Fragment>
                )
              })}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {missedCount > 0 && (
        <button
          className="jump-to-latest"
          onClick={handleJumpToLatest}
          aria-label={`Jump to latest — ${missedCount} new ${missedCount === 1 ? 'message' : 'messages'}`}
        >
          <span className="jump-count">{missedCount}</span>
          new {missedCount === 1 ? 'message' : 'messages'}
          <span className="jump-arrow" aria-hidden="true">&darr;</span>
        </button>
      )}
    </div>
  )
}
