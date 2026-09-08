import type { Message, MessageAnchor, MessageRef } from '../../../types'
import { passageKey } from '../../../lib/passageAnchor'
export { passageKey } from '../../../lib/passageAnchor'
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
  /** Retain the complete message so every shape uses the Record renderer. */
  message: Message
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
    out.push({ ...ref, label: ref.label || ref.id })
  }
  return out
}

export interface ToSurfaceOptions {
  userNames: Record<string, string>
  currentUserId: string | null
  /** The reader's last read receipt (or join time) in this room. */
  unreadSince?: string | null
  streamingIds?: readonly string[]
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
    const isStreaming = options.streamingIds?.includes(message.id) ?? false
    const created = new Date(message.created_at).getTime()
    return {
      message,
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
      topic: anchor?.label || messageRefs(message)[0]?.label || WHOLE_ROOM_TOPIC,
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

/** Alternate views over one conversation (SurfaceConversation). */
export type ConversationShape = 'stream' | 'discussion' | 'map' | 'tree' | 'lanes' | 'signal'

export const SHAPE_LABELS: Record<ConversationShape, string> = {
  stream: 'Stream',
  discussion: 'Threads',
  map: 'Map',
  tree: 'Tree',
  lanes: 'Lanes',
  signal: 'Signal',
}

/** Shapes that need the whole width of the surface. */
export const WIDE_SHAPES: ReadonlySet<ConversationShape> = new Set(['discussion', 'map', 'tree', 'lanes', 'signal'])

export interface DiscussionThread {
  id: string
  source: MessageRef | null
  roots: SurfaceMsg[]
  messages: SurfaceMsg[]
}

/** Group independent thoughts on the same passage; keep replies under their actual ancestor. */
export function discussionThreads(messages: SurfaceMsg[]): DiscussionThread[] {
  const byId = new Map(messages.map((message) => [message.id, message]))
  const groups = new Map<string, DiscussionThread>()
  for (const message of messages) {
    let root = message
    const visited = new Set([root.id])
    while (root.parentId && byId.has(root.parentId) && !visited.has(root.parentId)) {
      root = byId.get(root.parentId)!
      visited.add(root.id)
    }
    const source = root.refs.find((ref) => ref.entity === 'reading_items') ?? null
    const id = source?.quote ? passageKey(source) : root.id
    let group = groups.get(id)
    if (!group) {
      group = { id, source, roots: [], messages: [] }
      groups.set(id, group)
    }
    if (!group.roots.some((candidate) => candidate.id === root.id)) group.roots.push(root)
    group.messages.push(message)
  }
  return [...groups.values()]
}

export interface DiscussionMapNode {
  id: string
  kind: 'source' | 'passage' | 'thought'
  label: string
  text: string
  message?: SurfaceMsg
  ref?: MessageRef
  threadId?: string
}

export interface DiscussionMap {
  nodes: DiscussionMapNode[]
  edges: { from: string; to: string; kind: 'contains' | 'reply' | 'discusses' | 'cites' }[]
}

/** Map only persisted references and reply ancestry; prose never implies a relationship. */
export function discussionMap(threads: DiscussionThread[], selected: MessageRef | null): DiscussionMap {
  const nodes = new Map<string, DiscussionMapNode>()
  const edges: DiscussionMap['edges'] = []
  const messages = threads.flatMap((thread) => thread.messages)
  const byId = new Map(messages.map((message) => [message.id, message]))
  const addRef = (ref: MessageRef, message?: SurfaceMsg, threadId?: string): string => {
    const sourceId = `source:${ref.id}`
    if (!nodes.has(sourceId)) nodes.set(sourceId, { id: sourceId, kind: 'source', label: 'Source', text: ref.label, ref: { ...ref, quote: undefined, quote_occurrence: undefined } })
    if (!ref.quote) return sourceId
    const id = `passage:${passageKey(ref)}`
    if (!nodes.has(id)) {
      nodes.set(id, { id, kind: 'passage', label: ref.label, text: ref.quote, ref, message, threadId })
      edges.push({ from: sourceId, to: id, kind: 'contains' })
    }
    return id
  }
  if (selected?.entity === 'reading_items') addRef({ ...selected, quote: undefined, quote_occurrence: undefined })
  for (const thread of threads) {
    const origin = thread.source ? addRef(thread.source, thread.roots[0], thread.id) : null
    for (const message of thread.messages) {
      nodes.set(message.id, { id: message.id, kind: 'thought', label: message.author.name, text: message.text, message, threadId: thread.id })
      const parent = message.parentId ? byId.get(message.parentId) : undefined
      if (parent) edges.push({ from: parent.id, to: message.id, kind: 'reply' })
      else if (origin) edges.push({ from: origin, to: message.id, kind: 'discusses' })
      for (const ref of message.refs) {
        if (ref.entity !== 'reading_items') continue
        if (parent?.refs.some((candidate) => passageKey(candidate) === passageKey(ref))) continue
        if (!parent && thread.source && passageKey(thread.source) === passageKey(ref)) continue
        edges.push({ from: addRef(ref, message), to: message.id, kind: 'cites' })
      }
    }
  }
  return { nodes: [...nodes.values()], edges }
}

/** Search people's actual words and the full source labels/passages carried by their refs. */
export function searchDiscussionMap(graph: DiscussionMap, query: string): DiscussionMapNode[] {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return []
  return graph.nodes.filter((node) => {
    const refs = node.kind === 'thought' ? node.message?.refs ?? [] : []
    const text = [node.label, node.text, ...refs.flatMap((ref) => [ref.label, ref.quote ?? ''])].join(' ').toLocaleLowerCase()
    return terms.every((term) => text.includes(term))
  })
}

/** Focus a thought's actual ancestors and citations, or the thoughts directly citing a source/passage. */
export function focusDiscussionMap(graph: DiscussionMap, focusId: string | null, collapsed: ReadonlySet<string>): DiscussionMap {
  const ids = new Set(graph.nodes.map((node) => node.id))
  const focused = focusId !== null && ids.has(focusId)
  const visible = new Set<string>()
  const includeParents = (id: string): void => {
    if (visible.has(id)) return
    visible.add(id)
    for (const edge of graph.edges) if (edge.to === id) includeParents(edge.from)
  }
  if (focused) {
    includeParents(focusId)
    if (graph.nodes.find((node) => node.id === focusId)?.kind !== 'thought') {
      const contexts = new Set([focusId])
      for (const edge of graph.edges) if (edge.from === focusId && edge.kind === 'contains') contexts.add(edge.to)
      for (const edge of graph.edges) if (contexts.has(edge.from) && edge.kind !== 'contains') includeParents(edge.to)
    }
  } else {
    const hidden = new Set<string>()
    const hideChildren = (id: string): void => {
      for (const edge of graph.edges) if (edge.kind === 'reply' && edge.from === id && !hidden.has(edge.to)) {
        hidden.add(edge.to)
        hideChildren(edge.to)
      }
    }
    for (const id of collapsed) hideChildren(id)
    for (const id of ids) if (!hidden.has(id)) visible.add(id)
    // Hidden branches should not leave their otherwise unused citations floating in the map.
    for (const node of graph.nodes) if (node.kind === 'passage' && !graph.edges.some((edge) => edge.from === node.id && visible.has(edge.to))) visible.delete(node.id)
  }
  return { nodes: graph.nodes.filter((node) => visible.has(node.id)), edges: graph.edges.filter((edge) => visible.has(edge.from) && visible.has(edge.to)) }
}
