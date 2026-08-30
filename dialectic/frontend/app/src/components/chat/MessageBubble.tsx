import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { addressBlock, decorateMentions, type MentionContext } from '../../lib/mentions'
import type { Attachment, CommitmentProposal, Message, Reaction, ThesisSeed } from '../../types'
import type { FieldMark } from '../../types/workspace.ts'
import { api, type MessageDecisionExplain } from '../../lib/api'
import { localProposals, type LocalProposal } from '../../lib/proposalEnvelope'
import { useAppStore } from '../../stores/appStore'
import { useMessageDecisions } from '../../hooks/useMessageDecisions'
import { MessageAttachments } from './MessageAttachments'
import { SignatureMark } from './SignatureMark'
import { PassageMarker } from './PassageMarker'
import { RoundCard } from './RoundCard'
import { MessageMarks } from './MessageMarks'
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
  /**
   * The room's humans and the reader's own name, so @mentions can be
   * resolved and painted. Absent means render the text undecorated — a
   * mention chip for somebody the room does not have is worse than none.
   */
  mentionContext?: MentionContext
  /** Display names by user id — a forecaster must not render as a UUID. */
  userNames?: Record<string, string>
  /** Field marks whose subject is THIS message, with their review state. */
  marks?: FieldMark[]
  /** Re-read the Field projection after a mark or a review lands. */
  onFieldChanged?: () => void
  /** Same speaker continuing — avatar and byline are suppressed as repetition. */
  isContinuation?: boolean
  /** Media carried by this message, if any. */
  attachments?: Attachment[]
  /**
   * Opens the Bench, where the thesis is drafted and reviewed.
   *
   * WHY a callback and not a store write: the Bench is a SCENE now, and a
   * scene is a destination axis. Design v2 §5.7 gives navigation exactly one
   * owner (useRoomNavigation), so a card deep in the transcript must ask for
   * the destination rather than install one — otherwise the URL, the history
   * entry and the rendered scene can disagree. The seed rides along because
   * at Home the destination is a room that does not exist yet.
   */
  onOpenBench?: (seed: ThesisSeed) => void
}

/**
 * The first link in a message, so it can be filed into the library.
 *
 * Mirrors `first_url` in llm/claim_check.py — which is already what decides
 * whether a message gets claim-checked, so the two agree on what "this
 * message has a link" means.
 */
const URL_RE = /https?:\/\/[^\s<>"')]+/

function firstUrl(content: string): string | null {
  return URL_RE.exec(content)?.[0] ?? null
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

/**
 * Structural role only now — F1 dropped every visual difference this class
 * used to carry (bubble background, border hue, avatar color). What is left
 * is genuinely role-based, not participant-color-coded: the annotator's
 * reduced size/opacity marks it as marginalia, and the system class centers
 * a notice that is not a contribution at all. Neither varies by WHO is
 * speaking, only by WHAT KIND of turn it is (design v2 §16.4).
 */
function speakerClass(type: Message['speaker_type'], isSelf: boolean): string {
  if (type === 'human') return isSelf ? 'msg-human-self' : 'msg-human-other'
  if (type === 'llm_primary') return 'msg-claude'
  if (type === 'llm_provoker') return 'msg-provoker'
  if (type === 'llm_annotator') return 'msg-annotator'
  return 'msg-system'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

// ── provenance: why a machine message happened ──────────────────────────
//
// Owner's own words: "the user needs to be able to see EVERYWHERE what the
// fuck is going on." Machine messages carried no indication of why they
// exist — an answer to a question and an unprompted news alert looked
// identical. This section translates api/decisions.py's raw `reason`
// strings (llm/heuristics.py, llm/wire.py, llm/silence_sweep.py,
// llm/orchestrator.py) and messages.metadata.source into the reader's own
// terms. A raw reason string like "wire_interjection" must never reach the
// user verbatim.

/**
 * Reason strings the interjection engine can record on a SPOKEN decision.
 * Two are parameterized ("turn_threshold_exceeded (N >= M)",
 * "semantic_novelty_spike (0.NN)") and matched by prefix; everything else
 * is an exact reason string. `stagnation_detected` is HISTORICAL ONLY —
 * that rung was removed 2026-08-15 (dialectic/CLAUDE.md's amendment of that
 * date; llm/heuristics.py's `_detect_stagnation` is now a `return False`
 * stub) and cannot fire today, but old messages still carry the old reason
 * and must be described as history, not as a live feature.
 */
function reasonHeadline(reason: string): string {
  if (reason.startsWith('turn_threshold_exceeded')) {
    return 'A stretch of turns had passed with nothing from it.'
  }
  if (reason.startsWith('semantic_novelty_spike')) {
    return 'The conversation had shifted into territory it hadn’t weighed in on yet.'
  }
  switch (reason) {
    case 'explicit_mention':
      return 'You addressed it directly, by name.'
    case 'question_detected':
      return 'Your last message read as a question.'
    case 'information_gap':
      return 'It knew something from memory that hadn’t come up in the conversation yet.'
    case 'balance_redirect':
      return 'One of you had been quiet a while, relative to the room.'
    case 'wire_interjection':
      return 'A news story crossed the relevance threshold it holds for the linked thesis.'
    case 'world_interjection':
      return 'A live feed reported something inside geography this room placed and bound to the thesis.'
    case 'silence_follow_up':
      return 'It had asked something here and nobody had answered yet.'
    case 'protocol_active':
      return 'A structured protocol was running, and this was its turn.'
    case 'stagnation_detected':
      return 'A message-shape check used to fire on short, repetitive stretches — retired 2026-08-15. This message predates that.'
    case 'forced':
      return 'Something in the room asked it to respond directly.'
    default:
      return 'It decided to speak — the specific reason isn’t translated here yet.'
  }
}

/**
 * `messages.metadata.source` — a DIFFERENT, already-present provenance
 * channel from a decision's `reason`. `source` says which scheduled job
 * WROTE this message's content; a decision's `reason` says WHY the
 * interjection engine gave a turn to a message at all. api/decisions.py's
 * own module docstring verified (by reading every writer in llm/) that the
 * two channels were DISJOINT until 2026-08-29. Since then force_response
 * stamps `source` = its decision reason (wire_interjection,
 * silence_follow_up, protocol_active, forced) so the transcript can be
 * queried without joining llm_decisions. Those messages carry BOTH; the
 * decision wins below because it is the richer record, and its
 * reasonHeadline already translates every one of those reasons.
 */
function sourceHeadline(source: string): string | null {
  switch (source) {
    case 'reading_echo':
      return 'Another room read something that bears on this one — filed here overnight.'
    case 'night_shift':
      return 'Filed from the overnight pass against the live thesis.'
    case 'trading_curator':
      return 'The desk pushed a thesis update while you were away, and this flags what changed.'
    case 'deep_dive':
      return 'Posted as the brief from a Research run.'
    default:
      return null
  }
}

/**
 * The last resort: no decision record and no recognized metadata.source.
 * True of most llm_annotator notes (the annotator never logs a decision —
 * it runs a separate path entirely) and of any message old enough to
 * predate this record. Always returns something: the point of this
 * feature is that nothing machine-authored is unexplained, even when the
 * honest explanation is only "what kind of turn this is."
 */
function roleFallback(speakerType: Message['speaker_type']): string {
  switch (speakerType) {
    case 'llm_annotator':
      return 'A note left for whoever was offline — not a reply in the conversation.'
    case 'llm_provoker':
      return 'A provoker turn — no decision record survives for this one.'
    case 'llm_primary':
      return 'A primary turn — no decision record survives for this one.'
    case 'system':
      return 'A system notice, not a participant turn.'
    default:
      return 'Machine-authored — no further record survives for this one.'
  }
}

interface ProvenanceInfo {
  headline: string
  detail: string[]
}

/**
 * Composes the three channels above into one disclosure. Decision data
 * wins when present (it is the richest — a reason plus the inputs that
 * made it fire); metadata.source is the fallback when there is content
 * provenance but no decision (see sourceHeadline's docstring for why that
 * precedence, not the reverse); the role fallback never fails.
 */
function describeProvenance(
  speakerType: Message['speaker_type'],
  source: string | undefined,
  decision: MessageDecisionExplain | undefined,
): ProvenanceInfo {
  if (decision) {
    const detail: string[] = []
    if (decision.use_provoker) {
      detail.push('Sent in provoker mode — arguing a position, not settling one.')
    }
    if (
      typeof decision.human_turn_count === 'number'
      && decision.reason.startsWith('turn_threshold_exceeded')
    ) {
      const n = decision.human_turn_count
      detail.push(`${n} human turn${n === 1 ? '' : 's'} in a row before it spoke.`)
    }
    if (
      typeof decision.semantic_novelty === 'number'
      && decision.reason.startsWith('semantic_novelty_spike')
    ) {
      detail.push(`Novelty score ${decision.semantic_novelty.toFixed(2)} against its own threshold.`)
    }
    if (
      typeof decision.unsurfaced_memory_count === 'number'
      && decision.reason === 'information_gap'
    ) {
      const n = decision.unsurfaced_memory_count
      detail.push(`${n} unsurfaced memor${n === 1 ? 'y' : 'ies'} it judged relevant.`)
    }
    if (typeof decision.confidence === 'number') {
      detail.push(`Recorded confidence ${Math.round(decision.confidence * 100)}%.`)
    }
    return { headline: reasonHeadline(decision.reason), detail }
  }
  if (source) {
    const headline = sourceHeadline(source)
    if (headline) return { headline, detail: [] }
  }
  return { headline: roleFallback(speakerType), detail: [] }
}

/** Gap between the trigger and the panel, and the margin off the viewport
 * edge — same values and same reasoning as common/Explain.tsx's OFFSET /
 * VIEWPORT_MARGIN, so the two disclosures feel like one system. */
const WHY_OFFSET = 6
const WHY_MARGIN = 8

/**
 * The disclosure trigger + floating panel. Mirrors common/Explain.tsx's
 * accessibility contract exactly — a real <button> with aria-expanded,
 * Escape closes and returns focus, dismissed on outside-click and on
 * scroll — rather than reinventing it, because that contract (not the
 * component itself) is what dialectic/CLAUDE.md's accessibility gate
 * requires. Explain.tsx cannot be reused directly: it resolves `term`
 * through lib/glossary.ts's fixed vocabulary, and this content is dynamic
 * per message (a decision's reason, confidence and inputs), not a
 * glossary entry — and glossary.ts is out of this work's ownership to
 * extend. The POSITIONING is copied for the same reason Explain.tsx's own
 * comment names: this trigger sits inside `.msg`'s stacking context, and a
 * `position: absolute` panel gets painted over by a LATER message's own
 * byline (the exact bug PassageMarker.tsx shipped with once already).
 * `position: fixed` with viewport coordinates read from
 * getBoundingClientRect() is the one fix that actually holds here.
 */
function MessageProvenance({ info }: { info: ProvenanceInfo }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      setOpen(false)
      triggerRef.current?.focus()
    }
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node
      if (panelRef.current?.contains(target)) return
      if (triggerRef.current?.contains(target)) return
      setOpen(false)
    }
    function onScroll() {
      setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open])

  // Clamp inside the viewport after paint, once the panel's real size is
  // known — same reasoning as Explain.tsx's own layout effect.
  useLayoutEffect(() => {
    const panel = panelRef.current
    if (!open || !pos || !panel) return
    const rect = panel.getBoundingClientRect()
    let { top, left } = pos
    if (left + rect.width > window.innerWidth - WHY_MARGIN) {
      left = window.innerWidth - rect.width - WHY_MARGIN
    }
    if (left < WHY_MARGIN) left = WHY_MARGIN
    if (top + rect.height > window.innerHeight - WHY_MARGIN) {
      const trigger = triggerRef.current?.getBoundingClientRect()
      const above = (trigger ? trigger.top : top) - rect.height - WHY_OFFSET
      top = above >= WHY_MARGIN
        ? above
        : Math.max(WHY_MARGIN, window.innerHeight - rect.height - WHY_MARGIN)
    }
    panel.style.top = `${top}px`
    panel.style.left = `${left}px`
  }, [open, pos])

  function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    const rect = triggerRef.current?.getBoundingClientRect()
    setPos({ top: (rect?.bottom ?? 0) + WHY_OFFSET, left: rect?.left ?? 0 })
    setOpen(true)
  }

  return (
    <span className="msg-why">
      <button
        ref={triggerRef}
        type="button"
        className="msg-why-trigger"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label="Why this message appeared"
        onClick={toggle}
      >
        · why
      </button>
      {open && pos && (
        <div
          ref={panelRef}
          id={panelId}
          className="msg-why-panel"
          style={{ position: 'fixed', top: pos.top, left: pos.left }}
          role="note"
          aria-label="Why this message appeared"
        >
          <p className="msg-why-headline">{info.headline}</p>
          {info.detail.length > 0 && (
            <ul className="msg-why-detail">
              {info.detail.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
        </div>
      )}
    </span>
  )
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
  mentionContext,
  userNames = {},
  marks = [],
  onFieldChanged,
  isContinuation,
  attachments = [],
  onOpenBench,
}: MessageBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  const [showPicker, setShowPicker] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [acceptState, setAcceptState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const [readingAcceptState, setReadingAcceptState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const [resolutionState, setResolutionState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const [tradeState, setTradeState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const [fileState, setFileState] = useState<'idle' | 'filing' | 'filed' | 'error'>('idle')
  const editRef = useRef<HTMLTextAreaElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const currentRoomId = useAppStore((s) => s.currentRoom?.id)

  // Provenance — never on a human message. Fetched once per THREAD (see
  // useMessageDecisions.ts's own docstring for why calling it here, once
  // per rendered bubble, still costs the network exactly one request) and
  // looked up by this message's own id; `enabled` skips the subscribe and
  // the fetch entirely for a thread that turns out to hold no machine
  // messages at all.
  const isMachine = message.speaker_type !== 'human'
  const decisionsState = useMessageDecisions(currentRoomId, message.thread_id, isMachine)
  const decision = decisionsState.status === 'ready'
    ? decisionsState.decisions[message.id]
    : undefined
  const provenance = isMachine
    ? describeProvenance(message.speaker_type, message.metadata?.source, decision)
    : null

  const html = useMemo(() => {
    const raw = marked.parse(message.content, { async: false }) as string
    const clean = DOMPurify.sanitize(raw)
    // AFTER sanitize, never before: decorateMentions walks text nodes and adds
    // spans of its own making, so it cannot reintroduce anything DOMPurify
    // just removed. Running it first would hand DOMPurify our markup to strip.
    return mentionContext ? decorateMentions(clean, mentionContext) : clean
  }, [message.content, mentionContext])

  // Who this message opens by addressing — the same parse rung 0 of the
  // interjection ladder reads on the server (llm/mentions.addresses_someone_else).
  // With three humans in the room, "who is this for" stopped being inferable
  // from prose.
  const addressedTo = useMemo(
    () => (mentionContext ? addressBlock(message.content, mentionContext) : []),
    [message.content, mentionContext],
  )

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

  // A link in a HUMAN message can be filed into the library by anyone in the
  // room. Claude's own messages already have save_reading; the gap was that a
  // person pasting an article had no way to keep it.
  const pastedUrl = message.speaker_type === 'human' ? firstUrl(message.content) : null

  const fileReading = async () => {
    if (!pastedUrl || !currentRoomId) return
    setFileState('filing')
    try {
      await api.fileReading(currentRoomId, { message_id: message.id, url: pastedUrl })
      setFileState('filed')
    } catch {
      // Say so. A silent failure reads as "filed", which is the one thing it
      // must not imply about something you meant to keep.
      setFileState('error')
    }
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

  // Every proposal this message carries, in ONE shape (design v2 §8.3–8.4).
  //
  // WHY derived rather than five ad-hoc reads: each card used to compute its
  // own `Boolean(x?.accepted) || localState === 'accepted'`, which is the same
  // rule written five times — and the slot-to-kind table was written again on
  // the server. `lib/proposalEnvelope` holds it once, pinned to the backend's
  // copy by a test, so a card cannot decide on its own what counts as accepted.
  //
  // The optimistic set is this tab's own accept returning before its
  // MESSAGE_METADATA patch arrives; the failed set is the state no row can
  // hold, because a relay failure leaves the stored flag false ON PURPOSE so a
  // retry is a fresh accept rather than a conflict.
  const proposalOverrides = useMemo(() => {
    const accepted = new Set<string>()
    const failed = new Set<string>()
    const mark = (slot: string, state: string) => {
      const id = `proposal:${message.id}:${slot}`
      if (state === 'accepted') accepted.add(id)
      if (state === 'error') failed.add(id)
    }
    mark('proposal', acceptState)
    mark('reading_proposal', readingAcceptState)
    mark('resolution_proposal', resolutionState)
    mark('trade_proposal', tradeState)
    return { accepted, failed }
  }, [message.id, acceptState, readingAcceptState, resolutionState, tradeState])

  const proposalsBySlot = useMemo(() => {
    const map = new Map<string, LocalProposal>()
    for (const p of localProposals(message.id, message.metadata ?? undefined,
                                   proposalOverrides)) {
      map.set(p.index === null ? p.slot : `${p.slot}[${p.index}]`, p)
    }
    return map
  }, [message.id, message.metadata, proposalOverrides])

  // A drafted prediction, if this turn made one. The Accept tap is the ONLY
  // write — the tool itself logged nothing.
  const proposal = message.metadata?.proposal
  const proposalLogged = proposalsBySlot.get('proposal')?.status === 'accepted'

  // A proposed thesis, if this turn made one. Nothing exists yet — the tap
  // carries the seed up and the destination is decided above, where the
  // cascade is drafted and reviewed before anything is created.
  //
  // AMENDED 2026-08-15: this used to write setThesisSeed itself and then ask
  // for the Bench. That is only correct when the Bench is in THIS room. At
  // Home there is no Bench and thesis creation answers 409, so the tap
  // resolved to the default scene and did nothing — the dead end that pushed
  // general talk back out of the shared room. Home now spawns the scheme's
  // room, which is a ROOM SWITCH, and appStore clears thesisSeed on exactly
  // that. Seeding from here would be dropped in flight, so the seed travels
  // as an argument and whoever handles the move decides when to set it.
  const thesisProposal = message.metadata?.thesis_proposal
  const openThesisCreate = () => {
    if (!thesisProposal) return
    onOpenBench?.({
      title: thesisProposal.title,
      claim: thesisProposal.claim,
      monthlyBudget: thesisProposal.monthly_budget ?? 5000,
    })
  }

  // Detected implicit commitments ("I bet…"). Accept sends an ordinary
  // create_commitment over the live socket; the disarm arrives back as a
  // MESSAGE_METADATA broadcast with accepted=true, for both members.
  const commitmentProposals = message.metadata?.commitment_proposals ?? []

  // The claim checker's badge, when this message's linked article isn't
  // fairly represented. Read-only — unlike the proposal cards there is no
  // Accept; it is a nudge, not a decision.
  const claimCheck = message.metadata?.claim_check
  const [commitAccepting, setCommitAccepting] = useState<number | null>(null)
  const acceptCommitmentProposal = (p: CommitmentProposal, index: number) => {
    const state = useAppStore.getState()
    if (!state.wsSend || commitAccepting !== null) return
    setCommitAccepting(index)
    const ok = state.wsSend('create_commitment', {
      claim: p.claim,
      resolution_criteria: p.resolution_criteria,
      category: p.category,
      source_message_id: message.id,
      proposal_index: index,
      thread_id: state.currentThread?.id,
    })
    if (!ok) setCommitAccepting(null)
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

  // A drafted library entry, if this turn made one. Accept re-fetches the
  // page through the sidecar and files it; the server flips `accepted`.
  const readingProposal = message.metadata?.reading_proposal
  const readingFiled = proposalsBySlot.get('reading_proposal')?.status === 'accepted'

  const acceptReading = async () => {
    if (!currentRoomId || readingAcceptState === 'accepting' || readingFiled) return
    setReadingAcceptState('accepting')
    try {
      await api.acceptReading(currentRoomId, message.id)
      setReadingAcceptState('accepted')
    } catch {
      setReadingAcceptState('error')
    }
  }

  // A proposed paper trade, if this turn made one. The Accept tap is the
  // ONLY write — the desk logs the paired forecast into the claims ledger
  // first, then records the fill (or just the fill, when the proposal
  // carries the explicit DISCRETIONARY label instead of a forecast).
  const tradeProposal = message.metadata?.trade_proposal
  const tradeFilled = proposalsBySlot.get('trade_proposal')?.status === 'accepted'

  const acceptTrade = async () => {
    if (!currentRoomId || tradeState === 'accepting' || tradeFilled) return
    setTradeState('accepting')
    try {
      await api.acceptTrade(currentRoomId, message.id)
      setTradeState('accepted')
    } catch {
      setTradeState('error')
    }
  }

  // A deadline-watch resolution proposal, if this annotator note carries
  // one. The tap relays the human's verdict to tradingDesk; an `unclear`
  // verdict is evidence-only and renders no buttons.
  const resolutionProposal = message.metadata?.resolution_proposal
  const resolutionLogged = proposalsBySlot.get('resolution_proposal')?.status === 'accepted'

  const acceptResolution = async (verdict: 'correct' | 'incorrect') => {
    if (!currentRoomId || !resolutionProposal || resolutionState === 'accepting' || resolutionLogged) return
    setResolutionState('accepting')
    try {
      await api.acceptResolution(currentRoomId, resolutionProposal.prediction_id, verdict)
      setResolutionState('accepted')
    } catch {
      setResolutionState('error')
    }
  }

  return (
    <div
      className={`msg ${cls}${streamCls}${isContinuation ? ' msg-continuation' : ''}`}
      data-message-id={message.id}
    >
      <div className="msg-body">
        {!isContinuation && (
          <div className="msg-meta">
            <SignatureMark speakerType={message.speaker_type} authorName={authorName} />
            <span className="msg-author">{authorName}</span>
            <span className="msg-time">{formatTime(message.created_at)}</span>
            {message.message_type !== 'text' && (
              <span className="msg-type-badge">{message.message_type}</span>
            )}
            {message.edited_at && <span className="msg-edited" title="This message was edited">edited</span>}
            {(message.metadata?.tags ?? []).map((tag) => (
              <span key={tag} className={`msg-tag msg-tag-${tag}`}>#{tag}</span>
            ))}
            {addressedTo.length > 0 && (
              <span className="msg-addressed" title={`Addressed to ${addressedTo.join(', ')}`}>
                <span aria-hidden="true">→</span> {addressedTo.join(', ')}
              </span>
            )}
          </div>
        )}
        <div className={`msg-content-frame${isFolded ? ' msg-folded' : ''}`}>
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
            <div
              ref={contentRef}
              className="msg-content"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )}
          {isFolded && <div className="msg-fold-veil" aria-hidden="true" />}
          {/* Only real, persisted, unfolded prose can be marked: a streaming
              placeholder has no row to point a subject at, and a folded body
              would anchor a quote the reader cannot see. */}
          {currentRoomId && !isStreaming && !isEditing && !isFolded && (
            <PassageMarker
              roomId={currentRoomId}
              threadId={message.thread_id}
              messageId={message.id}
              containerRef={contentRef}
              onMarked={onFieldChanged}
            />
          )}
        </div>
        {currentRoomId && (
          <MessageMarks roomId={currentRoomId} marks={marks} onReviewed={onFieldChanged} />
        )}
        {currentRoomId && message.metadata?.question_round && (
          <RoundCard
            roomId={currentRoomId}
            messageId={message.id}
            userNames={userNames}
          />
        )}

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

        {/* Quiet, opt-in — never on a human message. provenance is non-null
            exactly when isMachine is true. */}
        {provenance && (
          <div className="msg-why-wrap">
            <MessageProvenance info={provenance} />
          </div>
        )}

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

        {tradeProposal && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">Proposed paper trade</div>
            <div className="msg-proposal-statement">
              {tradeProposal.side === 'sell' ? 'Sell' : 'Buy'}{' '}
              ${tradeProposal.dollars.toLocaleString()} {tradeProposal.symbol}
              {tradeProposal.node_id && ` · ${tradeProposal.node_id}`}
            </div>
            <div className="msg-proposal-meta">{tradeProposal.rationale}</div>
            {tradeProposal.prediction ? (
              <div className="msg-proposal-meta">
                stakes: {tradeProposal.prediction.statement} —{' '}
                {Math.round(tradeProposal.prediction.confidence * 100)}% by{' '}
                {tradeProposal.prediction.deadline}
              </div>
            ) : (
              <div className="msg-proposal-meta">
                DISCRETIONARY — unscored by the claims ledger
              </div>
            )}
            {tradeFilled ? (
              <span className="msg-proposal-logged">filled on the paper book</span>
            ) : (
              <button
                className="msg-proposal-accept"
                disabled={tradeState === 'accepting'}
                onClick={acceptTrade}
              >
                {tradeState === 'accepting' ? 'Filling…' : 'Accept'}
              </button>
            )}
            {tradeState === 'error' && !tradeFilled && (
              <span className="msg-proposal-error">could not fill — try again</span>
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

        {readingProposal && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">File in the library</div>
            <div className="msg-proposal-statement">
              {readingProposal.title || readingProposal.url}
            </div>
            <div className="msg-proposal-meta">
              {readingProposal.site && `${readingProposal.site} · `}
              {readingProposal.url}
            </div>
            <div className="msg-proposal-meta">{readingProposal.summary}</div>
            {readingFiled ? (
              <span className="msg-proposal-logged">filed in the library</span>
            ) : (
              <button
                className="msg-proposal-accept"
                disabled={readingAcceptState === 'accepting'}
                onClick={acceptReading}
              >
                {readingAcceptState === 'accepting' ? 'Filing…' : 'Accept'}
              </button>
            )}
            {readingAcceptState === 'error' && !readingFiled && (
              <span className="msg-proposal-error">could not file — try again</span>
            )}
          </div>
        )}

        {resolutionProposal && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">Prediction resolution</div>
            <div className="msg-proposal-statement">{resolutionProposal.statement}</div>
            <div className="msg-proposal-meta">
              verdict: {resolutionProposal.verdict} — {resolutionProposal.rationale}
            </div>
            {(resolutionProposal.evidence ?? []).length > 0 && (
              <div className="msg-proposal-meta">
                {(resolutionProposal.evidence ?? []).map((ev) => (
                  <div key={ev.url}>
                    <a
                      className="msg-claim-check-link"
                      href={ev.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {ev.title || ev.url}
                    </a>
                  </div>
                ))}
              </div>
            )}
            {resolutionLogged ? (
              <span className="msg-proposal-logged">resolution logged</span>
            ) : resolutionProposal.verdict !== 'unclear' ? (
              <div>
                <button
                  className="msg-proposal-accept"
                  disabled={resolutionState === 'accepting'}
                  onClick={() => acceptResolution('correct')}
                >
                  {resolutionState === 'accepting' ? 'Logging…' : 'Mark correct'}
                </button>
                <button
                  className="msg-proposal-accept"
                  disabled={resolutionState === 'accepting'}
                  onClick={() => acceptResolution('incorrect')}
                >
                  Mark incorrect
                </button>
              </div>
            ) : null}
            {resolutionState === 'error' && !resolutionLogged && (
              <span className="msg-proposal-error">could not log — try again</span>
            )}
          </div>
        )}

        {commitmentProposals.length > 0 && (
          <div className="msg-proposal">
            <div className="msg-proposal-title">Heard a commitment</div>
            {commitmentProposals.map((p, i) => (
              <div key={i} className="msg-commitment-item">
                <div className="msg-proposal-statement">{p.claim}</div>
                <div className="msg-proposal-meta">
                  {p.category} · resolves when: {p.resolution_criteria}
                </div>
                {proposalsBySlot.get(`commitment_proposals[${i}]`)?.status
                  === 'accepted' ? (
                  <span className="msg-proposal-logged">on the record</span>
                ) : (
                  <button
                    className="msg-proposal-accept"
                    disabled={commitAccepting !== null}
                    onClick={() => acceptCommitmentProposal(p, i)}
                  >
                    {commitAccepting === i ? 'Logging…' : 'Put it on record'}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {claimCheck && (
          <div className="msg-claim-check">
            <div className="msg-proposal-title">
              ⚠ {claimCheck.verdict === 'misrepresented'
                ? 'misrepresents the linked article'
                : 'only partly matches the linked article'}
            </div>
            {claimCheck.note && (
              <div className="msg-proposal-meta">{claimCheck.note}</div>
            )}
            <div className="msg-proposal-meta">
              <a
                className="msg-claim-check-link"
                href={claimCheck.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {claimCheck.title || claimCheck.url}
              </a>
            </div>
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
        {pastedUrl && !isStreaming && (
          <button
            className="msg-action-btn"
            onClick={fileReading}
            disabled={fileState === 'filing' || fileState === 'filed'}
            title={fileState === 'filed' ? 'In the library' : `File ${pastedUrl} into the library`}
          >
            {fileState === 'filed' ? 'FILED' : fileState === 'filing' ? 'FILING…'
              : fileState === 'error' ? 'RETRY FILE' : 'FILE'}
          </button>
        )}
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
