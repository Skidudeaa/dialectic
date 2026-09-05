import { useEffect, useMemo, useRef, useState } from 'react'
import type { Attachment, DailyActivity, Message, MessageAnchor, MessageRef } from '../../../types'
import { api } from '../../../lib/api.ts'
import { MessageInput, type MessageInputHandle } from '../../chat/MessageInput'
import { TypingIndicator } from '../../chat/TypingIndicator'
import type { MessageListProps } from '../../chat/MessageList'
import { SurfaceEvidence } from './SurfaceEvidence'
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
  ) => boolean | Promise<boolean>
  onTypingStart: () => void
  onTypingStop: () => void
  onTypingContent: (content: string) => void
  disabled: boolean
  memberNames: string[]
  draft?: string
}

export interface SurfaceConversationProps {
  roomId: string
  messages: SurfaceMsg[]
  humans: SurfaceAuthor[]
  shape: ConversationShape
  onShape: (shape: ConversationShape) => void
  /** The stream takes the whole width (the wide shapes always do). */
  wide: boolean
  onToggleWide: () => void
  /** The focused node or disputed edge — what the composer lands on. */
  anchor: MessageAnchor | null
  onClearAnchor: () => void
  onAnchor: (anchor: MessageAnchor) => void
  /** Refs staged for the next message (an update dropped onto a node). */
  pendingRefs: MessageRef[]
  onRemovePendingRef: (ref: MessageRef) => void
  onClearPendingRefs: (sentRefs: MessageRef[]) => void
  composer: SurfaceComposer
  composerRef: React.Ref<MessageInputHandle>
  typingUsers: string[]
  activityLabel: string | null
  onOpenRef: (ref: MessageRef) => void
  onFork: (messageId: string) => void
  annotatorEnabled: boolean | null
  addressedOnly: boolean | null
  controls: MessageListProps
  selectedEvidence: MessageRef | null
  onSelectEvidence: (ref: MessageRef | null) => void
  onStageRef: (ref: MessageRef) => void
  onOpenFull: (ref: MessageRef) => void
  evidenceOpen: boolean
  onEvidenceOpen: (open: boolean) => void
  banners?: React.ReactNode
}

export function SurfaceConversation({
  roomId, messages, humans, shape, onShape, wide, onToggleWide, anchor, onClearAnchor, onAnchor,
  pendingRefs, onRemovePendingRef, onClearPendingRefs, composer, composerRef,
  typingUsers, activityLabel, onOpenRef, onFork, annotatorEnabled, addressedOnly,
  controls, selectedEvidence, onSelectEvidence, onStageRef, onOpenFull, banners, evidenceOpen, onEvidenceOpen,
}: SurfaceConversationProps) {
  const [onlyAnchored, setOnlyAnchored] = useState(false)
  const [replyToId, setReplyToId] = useState<string | null>(null)
  const [localJump, setLocalJump] = useState<{ id: string; nonce: number } | null>(null)
  const rootRef = useRef<HTMLElement>(null)
  const [compactPane, setCompactPane] = useState(() => window.innerWidth <= 760)
  useEffect(() => {
    if (!rootRef.current || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setCompactPane(entry.contentRect.width <= 760))
    observer.observe(rootRef.current)
    return () => observer.disconnect()
  }, [])

  function reply(id: string) {
    const message = messages.find((candidate) => candidate.id === id)
    if (!message || message.isStreaming) return
    setReplyToId(id)
    if (message.anchor) onAnchor(message.anchor)
    else onClearAnchor()
    if (message.refs[0]) onSelectEvidence(message.refs[0])
    if (composerRef && 'current' in composerRef) composerRef.current?.focus()
  }

  const evidence = <SurfaceEvidence
    roomId={roomId} messages={messages} selected={selectedEvidence}
    onSelect={onSelectEvidence} onOpenFull={onOpenFull}
    onDiscuss={(ref) => { onStageRef(ref); onEvidenceOpen(false) }}
    onReply={(id) => { reply(id); onEvidenceOpen(false) }}
    onJump={(id) => { onShape('stream'); setOnlyAnchored(false); setLocalJump({ id, nonce: Date.now() }); onEvidenceOpen(false) }}
  />

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
    if (shown.length === 0 && shape !== 'stream') {
      return (
        <p className="surf-conv-empty">
          {anchor && onlyAnchored
            ? `Nothing said on ${anchor.label} yet — you could be first.`
            : 'Nothing here yet. Think out loud.'}
        </p>
      )
    }
    if (shape === 'tree') {
      return <ShapeTree messages={shown} controls={controls} onOpenRef={onOpenRef} onReply={reply} onFork={onFork} />
    }
    if (shape === 'lanes') {
      return <ShapeLanes messages={shown} controls={controls} humans={humans} onOpenRef={onOpenRef} onReply={reply} />
    }
    const jumpTarget = (localJump?.nonce ?? 0) > (controls.jumpTarget?.nonce ?? 0) ? localJump : controls.jumpTarget
    return <ShapeStream messages={shown} controls={{ ...controls, jumpTarget, contextRef: selectedEvidence,
      onSeen: evidenceOpen && compactPane ? undefined : controls.onSeen }}
      context={evidence} onOpenRef={onOpenRef} onReply={reply} onAnchor={onAnchor} />
  })()

  const placeholder = anchor
    ? `Think out loud… what you write lands on ${anchor.label}.`
    : pendingRefs.length ? 'What caught your attention? What does it change?'
    : 'Think out loud, share a link, or bring a source to the table…'

  return (
    <section ref={rootRef} className={`surf-conv${evidenceOpen ? ' surf-conv--evidence-open' : ''}`} aria-label="Conversation">
      <div className="surf-conv-head">
        <span className="surf-pane-lamp" aria-hidden="true" />
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
        <div className="surf-shapes surf-wide-toggle" role="group" aria-label="Conversation width">
          <button type="button" className="surf-shape surf-evidence-toggle" aria-pressed={evidenceOpen}
            aria-label={evidenceOpen ? 'Back to conversation' : 'Bring a source'}
            onClick={() => { onShape('stream'); onEvidenceOpen(!evidenceOpen) }}>
            {evidenceOpen ? 'Conversation' : 'Sources'}
          </button>
          <button
            type="button"
            className="surf-shape surf-shape--wide"
            aria-pressed={wide}
            title={wide ? 'Put the graph beside the conversation' : 'Give the conversation the whole width'}
            onClick={onToggleWide}
          >
            <span className="surf-grip" aria-hidden="true">⠿</span>
            {wide ? '⇥ Split' : '⇔ Wide'}
          </button>
        </div>
        <div className="surf-shapes" role="group" aria-label="Conversation shape">
          {(Object.keys(SHAPE_LABELS) as ConversationShape[]).map((candidate) => (
            <button
              key={candidate}
              type="button"
              className="surf-shape"
              aria-pressed={candidate === shape}
              onClick={() => { onEvidenceOpen(false); onShape(candidate) }}
            >
              {SHAPE_LABELS[candidate]}
            </button>
          ))}
        </div>
      </div>

      {banners && <div className="surf-conv-banners">{banners}</div>}
      <div className={`surf-conv-body${shape === 'stream' ? '' : ' surf-conv-body--scroll'}`}>
        {body}
      </div>

      <div className="surf-compose">
        <TypingIndicator typingUsers={typingUsers} activityLabel={activityLabel} />
        {(anchor || pendingRefs.length > 0 || Boolean(replyToId && messages.find((m) => m.id === replyToId)?.refs.length)) && (
          <div className="surf-compose-line">
            {anchor && <span>lands on</span>}
            {anchor ? (
              <span className="surf-chip surf-chip--anchor">
                {anchor.kind === 'edge' ? '⇢' : '⚒'} {anchor.label}
                <button type="button" aria-label={`Clear ${anchor.label}${replyToId ? ' and stop replying' : ''}`}
                  onClick={() => { onClearAnchor(); setReplyToId(null) }}>×</button>
              </span>
            ) : null}
            {pendingRefs.length > 0 && <span>attaching</span>}
            {pendingRefs.map((ref) => (
              <span key={`${ref.entity}:${ref.id}`} className="surf-chip">
                {refGlyph(ref.entity)} {ref.label}
                <button type="button" aria-label={`Remove ${ref.label}`} onClick={() => onRemovePendingRef(ref)}>×</button>
              </span>
            ))}
            {replyToId && pendingRefs.length === 0 && messages.find((m) => m.id === replyToId)?.refs.map((ref) => (
              <span key={`${ref.entity}:${ref.id}`} className="surf-chip">Reply keeps {ref.label}</span>
            ))}
          </div>
        )}
        {pendingRefs.some((ref) => ref.quote) && <div className="surf-compose-passages" aria-label="Passages attached to your next message">
          {pendingRefs.filter((ref) => ref.quote).map((ref) => <blockquote key={ref.id}><span>{ref.label}</span>{ref.quote}</blockquote>)}
        </div>}
        <MessageInput
          compactOptions
          roomId={roomId}
          composerRef={composerRef}
          initialValue={composer.draft}
          memberNames={composer.memberNames}
          placeholder={placeholder}
          disabled={composer.disabled}
          replyTo={replyTarget}
          onCancelReply={() => setReplyToId(null)}
          onTypingStart={composer.onTypingStart}
          onTypingStop={composer.onTypingStop}
          onTypingContent={composer.onTypingContent}
          onSend={async (content, messageType, files: Attachment[], tags) => {
            const sent = await composer.send(content, messageType, files.map((f) => f.id), tags, {
              replyToId: replyTarget ? replyToId : null,
              anchor,
              refs: pendingRefs,
            })
            if (!sent) return false
            setReplyToId((current) => current === replyToId ? null : current)
            onClearPendingRefs(pendingRefs)
            return true
          }}
        />
      </div>
    </section>
  )
}
