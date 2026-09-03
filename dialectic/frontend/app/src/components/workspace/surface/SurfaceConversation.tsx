import { useEffect, useMemo, useRef, useState } from 'react'
import type { Attachment, DailyActivity, Message, MessageAnchor, MessageRef } from '../../../types'
import { api } from '../../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { MessageInput, type MessageInputHandle } from '../../chat/MessageInput'
import { TypingIndicator } from '../../chat/TypingIndicator'
import { ShapeStream } from './shapes/ShapeStream'
import { ShapeTree } from './shapes/ShapeTree'
import { ShapeLanes } from './shapes/ShapeLanes'
import { ShapeSignal } from './shapes/ShapeSignal'
import {
  SHAPE_LABELS, refGlyph, type ConversationShape, type SurfaceAuthor, type SurfaceMsg,
} from './surfaceModel.ts'

type MessageType = Message['message_type']

/**
 * The four shapes over ONE conversation (the four-shapes prototype, ported):
 * the stream with its context rail, the tree of replies, lanes per person,
 * and the volume chart the enjoyment experiment is measured by. One
 * switcher, one message list, one composer.
 */
export interface SurfaceComposer {
  send: (
    content: string,
    messageType: MessageType,
    attachmentIds: string[],
    tags: string[],
    opts: { replyToId: string | null; anchor: MessageAnchor | null; refs: MessageRef[] },
  ) => boolean
  onTypingStart: () => void
  onTypingStop: () => void
  onTypingContent: (content: string) => void
  disabled: boolean
  memberNames: string[]
}

export interface SurfaceConversationProps {
  roomId: string
  messages: SurfaceMsg[]
  humans: SurfaceAuthor[]
  shape: ConversationShape
  onShape: (shape: ConversationShape) => void
  /** The focused node or disputed edge — what the composer lands on. */
  anchor: MessageAnchor | null
  onClearAnchor: () => void
  onAnchor: (anchor: MessageAnchor) => void
  /** Refs staged for the next message (an update dropped onto a node). */
  pendingRefs: MessageRef[]
  onRemovePendingRef: (ref: MessageRef) => void
  onClearPendingRefs: () => void
  composer: SurfaceComposer
  composerRef: React.Ref<MessageInputHandle>
  typingUsers: string[]
  activityLabel: string | null
  onOpenRef: (ref: MessageRef) => void
  onFork: (messageId: string) => void
  annotatorEnabled: boolean | null
  addressedOnly: boolean | null
}

export function SurfaceConversation({
  roomId, messages, humans, shape, onShape, anchor, onClearAnchor, onAnchor,
  pendingRefs, onRemovePendingRef, onClearPendingRefs, composer, composerRef,
  typingUsers, activityLabel, onOpenRef, onFork, annotatorEnabled, addressedOnly,
}: SurfaceConversationProps) {
  const [onlyAnchored, setOnlyAnchored] = useState(false)
  const [replyToId, setReplyToId] = useState<string | null>(null)

  const shown = useMemo(() => {
    if (!anchor || !onlyAnchored) return messages
    return messages.filter((m) => m.anchor?.id === anchor.id)
  }, [messages, anchor, onlyAnchored])

  // A reply target belongs to the messages on screen; resolve, never store.
  const replyTarget = useMemo(() => {
    if (!replyToId) return null
    const target = messages.find((m) => m.id === replyToId)
    return target ? { author: target.author.name, content: target.text } : null
  }, [replyToId, messages])

  // The volume chart reads the server's per-day counts, only while showing.
  const [activity, setActivity] = useState<
    { status: 'loading' } | { status: 'ready'; data: DailyActivity } | { status: 'unavailable'; error: string }
  >({ status: 'loading' })
  const activityTicket = useRef(0)
  useEffect(() => {
    if (shape !== 'signal') return
    const ticket = ++activityTicket.current
    void (async () => {
      await Promise.resolve()
      if (activityTicket.current !== ticket) return
      setActivity({ status: 'loading' })
      try {
        const data = await api.getDailyActivity(roomId, 14)
        if (activityTicket.current === ticket) setActivity({ status: 'ready', data })
      } catch (error: unknown) {
        if (activityTicket.current === ticket) {
          setActivity({ status: 'unavailable', error: error instanceof Error ? error.message : 'Could not read the last 14 days' })
        }
      }
    })()
  }, [shape, roomId])

  const humanCount = shown.filter((m) => m.author.kind === 'human').length
  const machineCount = shown.filter((m) => m.author.kind === 'machine').length

  const body = (() => {
    if (shape === 'signal') {
      return (
        <ShapeSignal
          activity={activity.status === 'ready' ? activity.data : null}
          status={activity.status}
          error={activity.status === 'unavailable' ? activity.error : undefined}
          annotatorEnabled={annotatorEnabled}
          addressedOnly={addressedOnly}
        />
      )
    }
    if (shown.length === 0) {
      return (
        <p className="surf-conv-empty">
          {anchor && onlyAnchored
            ? `Nothing said on ${anchor.label} yet — you could be first.`
            : 'Nothing here yet. Think out loud.'}
        </p>
      )
    }
    if (shape === 'tree') {
      return <ShapeTree messages={shown} onOpenRef={onOpenRef} onReply={setReplyToId} onFork={onFork} />
    }
    if (shape === 'lanes') {
      return <ShapeLanes messages={shown} humans={humans} onOpenRef={onOpenRef} onReply={setReplyToId} />
    }
    return <ShapeStream messages={shown} onOpenRef={onOpenRef} onReply={setReplyToId} onAnchor={onAnchor} />
  })()

  const placeholder = anchor
    ? `Think out loud… what you write lands on ${anchor.label}.`
    : `Think out loud… it lands on the whole room. Focus a node to speak to it.`

  return (
    <section className="surf-conv" aria-label="Conversation">
      <div className="surf-conv-head">
        <span className="surf-conv-kicker">
          Conversation · <b>{anchor && onlyAnchored ? anchor.label : 'whole room'}</b>
          {' · '}{humanCount} human · {machineCount} machine
        </span>
        {anchor && (
          <label className="surf-conv-filter">
            <input
              type="checkbox"
              checked={onlyAnchored}
              onChange={(e) => setOnlyAnchored(e.target.checked)}
            />
            only on {anchor.label}
          </label>
        )}
        <div className="surf-shapes" role="group" aria-label="Conversation shape">
          {(Object.keys(SHAPE_LABELS) as ConversationShape[]).map((candidate) => (
            <button
              key={candidate}
              type="button"
              className="surf-shape"
              aria-pressed={candidate === shape}
              onClick={() => onShape(candidate)}
            >
              {SHAPE_LABELS[candidate]}
            </button>
          ))}
        </div>
      </div>

      <div className={`surf-conv-body${shape === 'stream' ? '' : ' surf-conv-body--scroll'}`}>
        {body}
      </div>

      <div className="surf-compose">
        <TypingIndicator typingUsers={typingUsers} activityLabel={activityLabel} />
        {(anchor || pendingRefs.length > 0) && (
          <div className="surf-compose-line">
            <span>lands on</span>
            {anchor ? (
              <span className="surf-chip surf-chip--anchor">
                {anchor.kind === 'edge' ? '⇢' : '⚒'} {anchor.label}
                <button type="button" aria-label={`Stop speaking to ${anchor.label}`} onClick={onClearAnchor}>×</button>
              </span>
            ) : (
              <span className="surf-chip">the whole room</span>
            )}
            {pendingRefs.length > 0 && <span>attaching</span>}
            {pendingRefs.map((ref) => (
              <span key={`${ref.entity}:${ref.id}`} className="surf-chip">
                {refGlyph(ref.entity)} {ref.label}
                <button type="button" aria-label={`Remove ${ref.label}`} onClick={() => onRemovePendingRef(ref)}>×</button>
              </span>
            ))}
          </div>
        )}
        <MessageInput
          roomId={roomId}
          composerRef={composerRef}
          memberNames={composer.memberNames}
          placeholder={placeholder}
          disabled={composer.disabled}
          replyTo={replyTarget}
          onCancelReply={() => setReplyToId(null)}
          onTypingStart={composer.onTypingStart}
          onTypingStop={composer.onTypingStop}
          onTypingContent={composer.onTypingContent}
          onSend={(content, messageType, files: Attachment[], tags) => {
            const sent = composer.send(content, messageType, files.map((f) => f.id), tags, {
              replyToId: replyTarget ? replyToId : null,
              anchor,
              refs: pendingRefs,
            })
            if (!sent) return false
            setReplyToId(null)
            onClearPendingRefs()
            return true
          }}
        />
        <p className="surf-compose-line surf-compose-line--foot">
          @{PARTICIPANT_NAME} to ask it · paste a link to read it
        </p>
      </div>
    </section>
  )
}
