import type { Message, MessageAnchor, MessageRef } from '../../../types'
import { PARTICIPANT_NAME, markGlyph } from '../../../lib/productIdentity.ts'

/**
 * The working surface's ONE view of a message, shared by every conversation
 * shape (stream, tree, lanes, signal) and by the graph's human-word slots.
 *
 * WHY a view model and not the raw Message: four shapes reading
 * `metadata?.anchor`, `metadata?.refs`, `metadata?.tools?.calls`,
 * `references_message_id` and the speaker/name resolution each in their own
 * way is four copies of one rule. Derive once here; the shapes render.
 */
export type SurfaceAuthorKind = 'human' | 'machine' | 'system'

export interface SurfaceAuthor {
  /** `user_id` for a human, `'dialectic'` for the participant, `'system'`. */
  id: string
  name: string
  kind: SurfaceAuthorKind
  /** The signature glyph the transcript already uses (markGlyph). */
  glyph: string
  /** Which voice, for a machine message. */
  role?: 'primary' | 'provoker' | 'annotator'
  /** True for the reader's own messages. */
  isSelf: boolean
}

export interface SurfaceTool {
  name: string
  label: string
  ok: boolean
}

export interface SurfaceMsg {
  id: string
  author: SurfaceAuthor
  /** ISO timestamp, verbatim. */
  createdAt: string
  /** `HH:MM` for today, `Sep 1 · HH:MM` otherwise — local time. */
  time: string
  text: string
  anchor: MessageAnchor | null
  refs: MessageRef[]
  /** The message this one replies to, when that message is in the window. */
  parentId: string | null
  tools: SurfaceTool[]
  /** Written by someone else after the reader's last read receipt. */
  isNew: boolean
  /** The in-flight LLM stream placeholder. */
  isStreaming: boolean
  /** The band a message belongs to on the surface: its anchor's label, or
   *  the whole room. */
  topic: string
}

export const WHOLE_ROOM_TOPIC = 'the whole room'

const MACHINE_ROLE: Partial<Record<Message['speaker_type'], SurfaceAuthor['role']>> = {
  llm_primary: 'primary',
  llm_provoker: 'provoker',
  llm_annotator: 'annotator',
}

export function formatSurfaceTime(iso: string, now: Date = new Date()): string {
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ''
  const hhmm = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const sameDay = when.getFullYear() === now.getFullYear()
    && when.getMonth() === now.getMonth()
    && when.getDate() === now.getDate()
  if (sameDay) return hhmm
  const day = when.toLocaleDateString([], { month: 'short', day: 'numeric' })
  return `${day} · ${hhmm}`
}

export function surfaceAuthor(
  message: Pick<Message, 'speaker_type' | 'user_id' | 'user_name'>,
  userNames: Record<string, string>,
  currentUserId: string | null,
): SurfaceAuthor {
  if (message.speaker_type === 'human') {
    const name = message.user_name
      ?? (message.user_id ? userNames[message.user_id] : undefined)
      ?? 'Human'
    return {
      id: message.user_id ?? 'human',
      name,
      kind: 'human',
      glyph: markGlyph('human', name),
      isSelf: Boolean(currentUserId && message.user_id === currentUserId),
    }
  }
  if (message.speaker_type === 'system') {
    return { id: 'system', name: 'System', kind: 'system', glyph: markGlyph('system', 'System'), isSelf: false }
  }
  return {
    id: 'dialectic',
    name: PARTICIPANT_NAME,
    kind: 'machine',
    glyph: markGlyph(message.speaker_type, PARTICIPANT_NAME),
    role: MACHINE_ROLE[message.speaker_type],
    isSelf: false,
  }
}

/** Every object a message carries, deduplicated by (entity, id). Explicit
 *  `refs` first; a proposal's own objects are not refs (they are not yet
 *  rows) and are deliberately not synthesized here. */
export function messageRefs(message: Pick<Message, 'metadata'>): MessageRef[] {
  const seen = new Set<string>()
  const out: MessageRef[] = []
  for (const ref of message.metadata?.refs ?? []) {
    if (!ref || typeof ref.entity !== 'string' || typeof ref.id !== 'string') continue
    const key = `${ref.entity}:${ref.id}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ entity: ref.entity, id: ref.id, label: ref.label || ref.id })
  }
  return out
}

export interface ToSurfaceOptions {
  userNames: Record<string, string>
  currentUserId: string | null
  /** The reader's last read receipt (or join time) in this room. */
  unreadSince?: string | null
  streamingId?: string | null
  now?: Date
}

export function toSurfaceMessages(messages: Message[], options: ToSurfaceOptions): SurfaceMsg[] {
  const ids = new Set(messages.map((m) => m.id))
  const since = options.unreadSince ? new Date(options.unreadSince).getTime() : null
  const now = options.now ?? new Date()
  return messages.map((message) => {
    const author = surfaceAuthor(message, options.userNames, options.currentUserId)
    const anchor = message.metadata?.anchor ?? null
    const parent = message.references_message_id ?? null
    const calls = message.metadata?.tools?.calls ?? []
    const isStreaming = message.id === options.streamingId
    const created = new Date(message.created_at).getTime()
    return {
      id: message.id,
      author,
      createdAt: message.created_at,
      time: formatSurfaceTime(message.created_at, now),
      text: message.content,
      anchor: anchor && anchor.kind && anchor.id ? anchor : null,
      refs: messageRefs(message),
      parentId: parent && ids.has(parent) ? parent : null,
      tools: calls.map((call) => ({ name: call.name, label: call.label ?? call.name, ok: call.ok })),
      isNew: since !== null && !author.isSelf && !isStreaming && created > since,
      isStreaming,
      topic: anchor?.label || WHOLE_ROOM_TOPIC,
    }
  })
}

/** The last thing a human said ON each node — the graph's "human word". */
export interface HumanWord {
  nodeId: string
  authorName: string
  createdAt: string
  quote: string
}

export function humanWordsByNode(messages: SurfaceMsg[]): Record<string, HumanWord> {
  const out: Record<string, HumanWord> = {}
  for (const m of messages) {
    if (m.author.kind !== 'human' || !m.anchor || m.anchor.kind !== 'node') continue
    const prev = out[m.anchor.id]
    if (prev && prev.createdAt > m.createdAt) continue
    out[m.anchor.id] = {
      nodeId: m.anchor.id,
      authorName: m.author.name,
      createdAt: m.createdAt,
      quote: m.text,
    }
  }
  return out
}

/** The glyph a ref kind renders with — one table for every shape. */
export const REF_GLYPHS: Record<string, string> = {
  reading_items: '❧',
  world_observations: '◉',
  field_marks: '※',
  memories: '☰',
  messages: '¶',
  geo_scopes: '✦',
  commitments: '◇',
  thesis_node: '⚒',
}

export const REF_LABELS: Record<string, string> = {
  reading_items: 'reading',
  world_observations: 'contact',
  field_marks: 'mark',
  memories: 'memory',
  messages: 'message',
  geo_scopes: 'scope',
  commitments: 'commitment',
  thesis_node: 'node',
}

export function refGlyph(entity: string): string {
  return REF_GLYPHS[entity] ?? '·'
}

export function refKindLabel(entity: string): string {
  return REF_LABELS[entity] ?? entity
}

/**
 * The workspace-object id a ref opens in Focus, or null when Focus has no
 * page for that entity (a fire cell, a memory, a thesis node). Mirrors the
 * prefixes FocusSurface.tsx understands.
 */
export function refFocusId(ref: MessageRef): string | null {
  switch (ref.entity) {
    case 'reading_items': return `reading:${ref.id}`
    case 'field_marks': return `field_mark:${ref.id}`
    case 'geo_scopes': return `geo_scope:${ref.id}`
    default: return null
  }
}

export type { DailyActivity, DailyActivityRow } from '../../../types'

/** The four shapes over one conversation (SurfaceConversation). */
export type ConversationShape = 'stream' | 'tree' | 'lanes' | 'signal'

export const SHAPE_LABELS: Record<ConversationShape, string> = {
  stream: 'Stream',
  tree: 'Tree',
  lanes: 'Lanes',
  signal: 'Signal',
}

/** Shapes that need the whole width of the surface. */
export const WIDE_SHAPES: ReadonlySet<ConversationShape> = new Set(['tree', 'lanes', 'signal'])
