import { useEffect, useMemo, useRef, useState } from 'react'
import type { Attachment, DailyActivity, Message, MessageAnchor, MessageReceipt, MessageRef } from '../../../types'
import { api } from '../../../lib/api.ts'
import { MessageInput, type MessageInputHandle } from '../../chat/MessageInput'
import { TypingIndicator } from '../../chat/TypingIndicator'
import type { MessageListProps } from '../../chat/MessageList'
import type { InvestigateMode } from '../../chat/MessageBubble'
import { SurfaceEvidence } from './SurfaceEvidence'
import { ShapeStream } from './shapes/ShapeStream'
import { ShapeDiscussion } from './shapes/ShapeDiscussion'
import { ShapeTree } from './shapes/ShapeTree'
import { ShapeLanes } from './shapes/ShapeLanes'
import { ShapeSignal } from './shapes/ShapeSignal'
import {
  SHAPE_LABELS, discussionThreads, passageKey, refGlyph, type DiscussionThread, type ConversationShape, type SurfaceAuthor, type SurfaceMsg,
} from './surfaceModel.ts'

type MessageType = Message['message_type']

export interface SurfaceComposer {
  send: (
    content: string,
    messageType: MessageType,
    attachmentIds: string[],
    tags: string[],
    opts: { replyToId: string | null; anchor: MessageAnchor | null; refs: MessageRef[] },
  ) => MessageReceipt | false | Promise<MessageReceipt | false>
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
  onToggleWide?: () => void
  readingLayout?: boolean
  roomControls?: React.ReactNode
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
  controls, selectedEvidence, onSelectEvidence, onStageRef, onOpenFull, banners, evidenceOpen, onEvidenceOpen, readingLayout = false, roomControls,
}: SurfaceConversationProps) {
  const [onlyAnchored, setOnlyAnchored] = useState(false)
  const [activeThread, setActiveThread] = useState<string | null>(null)
  const [sourceScroll, setSourceScroll] = useState(0)
  const [connector, setConnector] = useState('')
  const [mapExpanded, setMapExpanded] = useState(true)
  const linkedShape = shape === 'discussion' || shape === 'map'
  const threads = useMemo(() => discussionThreads(messages), [messages])
  const passages = useMemo(() => [...new Map(messages.flatMap((message) => message.refs.filter((ref) => ref.entity === 'reading_items' && ref.quote)).map((ref) => [passageKey(ref), ref])).values()], [messages])
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
    const thread = threads.find((candidate) => candidate.messages.some((item) => item.id === id))
    setActiveThread(thread?.id ?? null)
    const source = message.refs.find((ref) => ref.entity === 'reading_items') ?? thread?.source ?? message.refs[0]
    if (source) { onSelectEvidence(source); setSourceScroll((n) => n + 1) }
    if (composerRef && 'current' in composerRef) composerRef.current?.focus()
  }

  /** The participant is a branch tool here: a person summons one compact
   *  evidence or challenge answer under the exact thought. The request stays
   *  editable; only Send runs anything. */
  function investigate(id: string, quote?: string, mode: InvestigateMode = 'evidence') {
    const message = messages.find((candidate) => candidate.id === id)
    if (!message || message.isStreaming) return
    reply(id)
    const part = quote ? `this part of ${message.author.name}’s thought:\n\n> ${quote}\n\n` : 'this thought. '
    const request = mode === 'challenge'
      ? `@Dialectic challenge ${part}Give the strongest specific counter-evidence or the weakest step in the reasoning, with a source where you can find one. Two or three sentences.`
      : quote
        ? `@Dialectic find and pull sources about ${part}Link what you find and briefly explain how it bears on this.`
        : '@Dialectic find and pull relevant sources for this thought. Link what you find and briefly explain what it adds.'
    if (composerRef && 'current' in composerRef) composerRef.current?.insert(request)
    onEvidenceOpen(false)
  }

  function selectThread(thread: DiscussionThread) {
    if (shape === 'map') setMapExpanded(false)
    setActiveThread(thread.id)
    if (thread.source) onSelectEvidence(thread.source)
    setSourceScroll((n) => n + 1)
    if (compactPane) onEvidenceOpen(true)
  }

  function jumpToThread(id: string, passage?: MessageRef) {
    const thread = threads.find((candidate) => candidate.messages.some((message) => message.id === id))
    const message = messages.find((candidate) => candidate.id === id)
    const source = passage ?? message?.refs.find((ref) => ref.entity === 'reading_items') ?? thread?.source
    if (source) { onSelectEvidence(source); setSourceScroll((n) => n + 1) }
    onShape('discussion')
    setOnlyAnchored(false)
    setActiveThread(thread?.id ?? null)
    setLocalJump({ id, nonce: Date.now() })
    onEvidenceOpen(false)
  }

  const evidence = <SurfaceEvidence
    roomId={roomId} messages={messages} selected={selectedEvidence}
    onSelect={onSelectEvidence} onOpenFull={onOpenFull}
    passages={passages} scrollRequest={sourceScroll}
    onPassage={(ref) => {
      const message = messages.find((candidate) => candidate.refs.some((source) => passageKey(source) === passageKey(ref)))
      if (message) jumpToThread(message.id, ref)
    }}
    onDiscuss={(ref) => { setReplyToId(null); onClearAnchor(); onStageRef(ref); onShape('discussion'); onEvidenceOpen(false) }}
    onInvestigate={(ref) => {
      setReplyToId(null); onClearAnchor(); onStageRef(ref); onShape('discussion'); onEvidenceOpen(false)
      if (composerRef && 'current' in composerRef) composerRef.current?.insert('@Dialectic find and pull sources about this passage. Link what you find and briefly explain how it bears on these words.')
    }}
    onAttach={replyToId ? (ref) => { onStageRef(ref); onEvidenceOpen(false) } : undefined}
    onReply={(id) => { reply(id); onEvidenceOpen(false) }}
    onJump={jumpToThread}
  />

  useEffect(() => {
    const root = rootRef.current
    if (!root || shape !== 'discussion' || compactPane || !selectedEvidence?.quote) return
    let frame = 0
    const measure = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const key = passageKey(selectedEvidence)
        const thread = [...root.querySelectorAll<HTMLElement>('[data-thread]')].find((node) => node.dataset.thread === activeThread)
        const header = [...(thread ?? root).querySelectorAll<HTMLElement>('[data-thread-anchor]')].find((node) => node.dataset.threadAnchor === key)
        const mark = [...root.querySelectorAll<HTMLElement>('mark[data-passage]')].find((node) => node.dataset.passage === key)
        const pane = root.querySelector('.surf-discussion')?.getBoundingClientRect()
        const article = root.querySelector('.surf-evidence')?.getBoundingClientRect()
        const a = header?.getBoundingClientRect(), b = mark?.getBoundingClientRect(), box = root.getBoundingClientRect()
        if (!a || !b || !pane || !article || a.bottom <= pane.top || a.top >= pane.bottom || b.bottom <= article.top + 60 || b.top >= article.bottom) { setConnector(''); return }
        const x1 = a.right - box.left, y1 = Math.max(a.top, pane.top) + Math.min(a.height, 50) / 2 - box.top
        const x2 = b.left - box.left, y2 = b.top + b.height / 2 - box.top
        const gutter = pane.right - box.left
        setConnector(`M${x1},${y1} H${gutter} V${y2} H${x2}`)
      })
    }
    const resize = new ResizeObserver(measure)
    resize.observe(root)
    const mutation = new MutationObserver(measure)
    mutation.observe(root, { childList: true, subtree: true })
    root.addEventListener('scroll', measure, true)
    measure()
    return () => { cancelAnimationFrame(frame); resize.disconnect(); mutation.disconnect(); root.removeEventListener('scroll', measure, true) }
  }, [shape, compactPane, selectedEvidence, activeThread, sourceScroll])

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

  const jumpTarget = (localJump?.nonce ?? 0) > (controls.jumpTarget?.nonce ?? 0) ? localJump : controls.jumpTarget

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
    if (linkedShape) return <ShapeDiscussion threads={onlyAnchored ? discussionThreads(shown) : threads} controls={controls} selected={selectedEvidence}
      active={activeThread} jump={jumpTarget} map={shape === 'map'} mapExpanded={mapExpanded} onToggleMap={() => { setMapExpanded((value) => !value); if (compactPane && mapExpanded) onEvidenceOpen(true) }} onSelect={selectThread}
      onOpenRef={(ref, messageId) => { if (messageId) setActiveThread(threads.find((thread) => thread.messages.some((message) => message.id === messageId))?.id ?? null); if (ref.entity === 'reading_items') { if (shape === 'map') setMapExpanded(false); onSelectEvidence(ref); setSourceScroll((n) => n + 1); if (compactPane) onEvidenceOpen(true) } else onOpenRef(ref) }}
      onReply={reply} onInvestigate={investigate} onJump={jumpToThread} />
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
    return <ShapeStream messages={shown} controls={{ ...controls, jumpTarget, contextRef: selectedEvidence,
      onSeen: evidenceOpen && compactPane ? undefined : controls.onSeen }}
      context={undefined} onOpenRef={onOpenRef} onReply={reply} onAnchor={onAnchor} />
  })()

  const placeholder = anchor
    ? `Think out loud… what you write lands on ${anchor.label}.`
    : pendingRefs.length ? 'What caught your attention? What does it change?'
    : 'Think out loud, share a link, or bring a source to the table…'

  return (
    <section ref={rootRef} className={`surf-conv${evidenceOpen ? ' surf-conv--evidence-open' : ''}${readingLayout && (shape === 'stream' || linkedShape) && !(shape === 'map' && mapExpanded) && !compactPane ? ' surf-conv--reading-layout' : ''}${linkedShape ? ' surf-conv--linked' : ''}${shape === 'map' && mapExpanded ? ' surf-conv--map-expanded' : ''}`} aria-label="Conversation">
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
            onClick={() => { setMapExpanded(false); if (!linkedShape && shape !== 'stream') onShape('discussion'); onEvidenceOpen(!evidenceOpen) }}>
            {evidenceOpen ? 'Conversation' : 'Sources'}
          </button>
          {onToggleWide && <button
            type="button"
            className="surf-shape surf-shape--wide"
            aria-pressed={wide}
            title={wide ? 'Put the graph beside the conversation' : 'Give the conversation the whole width'}
            onClick={onToggleWide}
          >
            <span className="surf-grip" aria-hidden="true">⠿</span>
            {wide ? '⇥ Split' : '⇔ Wide'}
          </button>}
        </div>
        <div className="surf-shapes" role="group" aria-label="Conversation shape">
          {(['discussion', 'map', 'stream'] as ConversationShape[]).map((candidate) => (
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
          <details className="surf-other-shapes"><summary>{['tree', 'lanes', 'signal'].includes(shape) ? SHAPE_LABELS[shape] : 'More'}</summary>
            {(['tree', 'lanes', 'signal'] as ConversationShape[]).map((candidate) => <button type="button" className="surf-shape" key={candidate} aria-pressed={shape === candidate}
              onClick={(event) => { onEvidenceOpen(false); onShape(candidate); event.currentTarget.closest('details')?.removeAttribute('open') }}>{SHAPE_LABELS[candidate]}</button>)}
          </details>
        </div>
        {roomControls}
      </div>

      {banners && <div className="surf-conv-banners">{banners}</div>}
      <div className={`surf-conv-body${shape === 'stream' || linkedShape ? ' surf-conv-body--context' : ' surf-conv-body--scroll'}`}>
        {body}
        {(shape === 'stream' || linkedShape) && evidence}
      </div>
      {shape === 'discussion' && !compactPane && connector && <svg className="surf-passage-link" aria-hidden="true"><path d={connector} /></svg>}

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
            if (rootRef.current) jumpToThread(sent.id)
            return true
          }}
        />
      </div>
    </section>
  )
}
