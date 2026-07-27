import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
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

/**
 * How close to the bottom counts as "following the conversation". Slightly more
 * than one line of text, so a stray trackpad nudge doesn't drop you out of
 * follow mode.
 */
const FOLLOW_THRESHOLD_PX = 120

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

  // Parent lookup for reply quoting. The referenced message may be outside the
  // loaded window (older than the fetched page), in which case the bubble
  // renders an unresolved-reference placeholder instead of pretending.
  const messagesById = useMemo(() => {
    const map = new Map<string, Message>()
    for (const msg of messages) map.set(msg.id, msg)
    return map
  }, [messages])

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
              {group.messages.map(msg => {
                const parent = msg.references_message_id
                  ? messagesById.get(msg.references_message_id)
                  : undefined
                return (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    isSelf={msg.user_id === currentUserId}
                    authorName={getAuthorName(msg, userNames)}
                    onFork={onFork}
                    onReply={onReply}
                    isStreaming={msg.id === streamingMessageId}
                    replyToAuthor={parent ? getAuthorName(parent, userNames) : undefined}
                    replyToContent={parent?.content}
                    replyToMissing={Boolean(msg.references_message_id && !parent)}
                  />
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
