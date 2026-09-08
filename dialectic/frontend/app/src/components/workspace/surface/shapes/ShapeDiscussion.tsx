import { useEffect, useMemo, useRef, useState } from 'react'
import type { MessageRef } from '../../../../types'
import type { MessageListProps } from '../../../chat/MessageList'
import { SurfaceMessage } from './SurfaceMessage'
import { passageKey, type DiscussionThread, type SurfaceMsg } from '../surfaceModel'
import './shapes.css'

interface Props {
  threads: DiscussionThread[]
  controls: MessageListProps
  selected: MessageRef | null
  active: string | null
  jump: { id: string; nonce: number } | null | undefined
  map: boolean
  mapExpanded?: boolean
  onToggleMap?: () => void
  onSelect: (thread: DiscussionThread) => void
  onOpenRef: (ref: MessageRef, messageId?: string) => void
  onReply: (id: string) => void
  onJump: (id: string) => void
}

/** Compact branches and the map navigate the same persisted quotations and replies. */
export function ShapeDiscussion({ threads, controls, selected, active, jump, map, mapExpanded, onToggleMap, onSelect, onOpenRef, onReply, onJump }: Props) {
  const onSeen = controls.onSeen
  const rootRef = useRef<HTMLDivElement>(null)
  const lastSeen = useRef(-1)
  const lastJump = useRef<number | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [zoom, setZoom] = useState(1)
  const messages = useMemo(() => threads.flatMap((thread) => thread.messages), [threads])
  const children = useMemo(() => {
    const result = new Map<string, SurfaceMsg[]>()
    for (const message of messages) if (message.parentId) {
      result.set(message.parentId, [...(result.get(message.parentId) ?? []), message])
    }
    return result
  }, [messages])
  useEffect(() => {
    if (!jump || map) return
    const node = [...(rootRef.current?.querySelectorAll<HTMLElement>('[data-mid]') ?? [])].find((candidate) => candidate.dataset.mid === jump.id)
    // Scroll only the discussion pane; scrollIntoView can move the entire composer offscreen.
    if (node && rootRef.current) rootRef.current.scrollTop += node.getBoundingClientRect().top - rootRef.current.getBoundingClientRect().top - 90
  }, [jump, map, collapsed])

  useEffect(() => {
    if (!jump || map || lastJump.current === jump.nonce) return
    lastJump.current = jump.nonce
    const parents = new Set<string>()
    let target = messages.find((message) => message.id === jump.id)
    while (target?.parentId && !parents.has(target.parentId)) {
      parents.add(target.parentId)
      target = messages.find((message) => message.id === target!.parentId)
    }
    const frame = requestAnimationFrame(() => setCollapsed((current) => new Set([...current].filter((id) => !parents.has(id)))))
    return () => cancelAnimationFrame(frame)
  }, [jump, map, messages])

  useEffect(() => {
    const root = rootRef.current
    if (!root || map || !onSeen || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => {
      if (document.visibilityState === 'hidden') return
      const visible = new Set(entries.filter((entry) => entry.isIntersecting && entry.intersectionRatio >= .6).map((entry) => (entry.target as HTMLElement).dataset.mid))
      const newest = messages.filter((message) => !message.isStreaming && visible.has(message.id)).sort((a, b) => b.message.sequence - a.message.sequence)[0]
      if (newest && newest.message.sequence > lastSeen.current) {
        lastSeen.current = newest.message.sequence
        onSeen?.(newest.id)
      }
    }, { root, threshold: .6 })
    for (const node of root.querySelectorAll('[data-mid]')) observer.observe(node)
    return () => observer.disconnect()
  }, [map, messages, collapsed, onSeen])

  function branch(message: SurfaceMsg, depth: number, ancestors: Set<string>): React.ReactNode {
    if (ancestors.has(message.id)) return null
    const descendants = children.get(message.id) ?? []
    const closed = collapsed.has(message.id)
    return <div className="surf-branch" key={message.id} data-depth={depth} style={{ marginLeft: depth > 0 && depth <= 5 ? 'var(--reply-indent)' : 0 }}>
      <SurfaceMessage msg={message} compact controls={{ ...controls, contextRef: selected }} onReply={onReply} onOpenRef={(ref) => onOpenRef(ref, message.id)} threadSource={threads.find((thread) => thread.messages.some((item) => item.id === message.id))?.source ?? null} />
      {descendants.length > 0 && <button type="button" className="surf-branch-toggle" aria-expanded={!closed}
        onClick={() => setCollapsed((current) => { const next = new Set(current); if (closed) next.delete(message.id); else next.add(message.id); return next })}>
        {closed ? '+' : '−'} {descendants.length} {descendants.length === 1 ? 'reply' : 'replies'} to {message.author.name}
      </button>}
      {!closed && descendants.map((child) => branch(child, depth + 1, new Set([...ancestors, message.id])))}
    </div>
  }

  if (map) {
    const nodes: { id: string; x: number; y: number; label: string; text: string; open: () => void; kind: string }[] = []
    const edges: { from: string; to: string; kind: string }[] = []
    const sources = new Map<string, MessageRef>()
    if (selected?.entity === 'reading_items') sources.set(selected.id, selected)
    for (const message of messages) for (const ref of message.refs) if (ref.entity === 'reading_items') sources.set(ref.id, ref)
    let sourceRow = 0
    for (const ref of sources.values()) nodes.push({ id: `source:${ref.id}`, x: 0, y: sourceRow++ * 112, label: 'Source', text: ref.label, open: () => onOpenRef({ ...ref, quote: undefined }), kind: 'source' })
    let row = 0
    for (const thread of threads) {
      if (thread.source?.quote && !nodes.some((node) => node.id === `passage:${thread.id}`)) {
        nodes.push({ id: `passage:${thread.id}`, x: 270, y: row * 112, label: 'Passage', text: thread.source.quote, open: () => onSelect(thread), kind: 'passage' })
        edges.push({ from: `source:${thread.source.id}`, to: `passage:${thread.id}`, kind: 'contains' })
      }
      const placed = new Set<string>()
      const place = (message: SurfaceMsg, depth: number) => {
        if (placed.has(message.id)) return
        placed.add(message.id)
        nodes.push({ id: message.id, x: 540 + depth * 270, y: row++ * 112, label: message.author.name, text: message.text, open: () => onJump(message.id), kind: 'thought' })
        if (message.parentId && messages.some((parent) => parent.id === message.parentId)) edges.push({ from: message.parentId, to: message.id, kind: 'reply' })
        else if (thread.source) edges.push({ from: thread.source.quote ? `passage:${thread.id}` : `source:${thread.source.id}`, to: message.id, kind: 'discusses' })
        for (const ref of message.refs) {
          if (ref.entity !== 'reading_items') continue
          const parent = messages.find((candidate) => candidate.id === message.parentId)
          if (parent?.refs.some((candidate) => passageKey(candidate) === passageKey(ref))) continue
          if (!message.parentId && thread.source && passageKey(thread.source) === passageKey(ref)) continue
          const from = ref.quote ? `passage:${passageKey(ref)}` : `source:${ref.id}`
          if (ref.quote && !nodes.some((node) => node.id === from)) {
            nodes.push({ id: from, x: 270, y: 0, label: 'Passage', text: ref.quote, open: () => onOpenRef(ref, message.id), kind: 'passage' })
            edges.push({ from: `source:${ref.id}`, to: from, kind: 'contains' })
          }
          edges.push({ from, to: message.id, kind: 'cites' })
        }
        for (const child of children.get(message.id) ?? []) place(child, depth + 1)
      }
      for (const root of thread.roots) place(root, 0)
    }
    let passageRow = 0
    for (const node of nodes) if (node.kind === 'passage') node.y = passageRow++ * 112
    const byId = new Map(nodes.map((node) => [node.id, node]))
    const width = Math.max(800, ...nodes.map((node) => node.x + 260))
    const height = Math.max(240, ...nodes.map((node) => node.y + 112))
    return <div className="surf-discussion surf-mindmap">
      <div className="surf-map-tools">{onToggleMap && <button type="button" onClick={onToggleMap}>{mapExpanded ? 'Open article' : 'Expand map'}</button>}<span>Scroll to explore · select a thought to discuss it</span>
        <button type="button" aria-label="Zoom out map" disabled={zoom <= .5} onClick={() => setZoom((n) => Math.max(.5, n - .1))}>−</button>
        <button type="button" aria-label="Reset map zoom" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button type="button" aria-label="Zoom in map" disabled={zoom >= 1.5} onClick={() => setZoom((n) => Math.min(1.5, n + .1))}>+</button>
      </div>
      <div className="surf-map-scroll" tabIndex={0} aria-label="Mind map; scroll to explore, select a thought to open its thread">
        <div style={{ width: width * zoom, height: height * zoom }}>
          <div className="surf-map-canvas" style={{ width, height, transform: `scale(${zoom})` }}>
            <svg width={width} height={height} aria-hidden="true">{edges.map((edge, i) => {
              const from = byId.get(edge.from), to = byId.get(edge.to)
              if (!from || !to) return null
              return <path key={i} data-kind={edge.kind} d={`M${from.x + 240},${from.y + 42} C${from.x + 260},${from.y + 42} ${to.x - 20},${to.y + 42} ${to.x},${to.y + 42}`}><title>{edge.kind}</title></path>
            })}</svg>
            {nodes.map((node) => <button type="button" key={node.id} className={`surf-map-node surf-map-node--${node.kind}`} style={{ left: node.x, top: node.y }} onClick={node.open}>
              <b>{node.label}</b><span>{node.text || 'Open contribution'}</span>
            </button>)}
          </div>
        </div>
        {nodes.length === 0 && <p>Select a source or start a thought. The map grows from your discussion.</p>}
      </div>
    </div>
  }
  return <div ref={rootRef} className="surf-discussion" aria-label="Passage discussion threads">
    {threads.length === 0 && <p className="surf-conv-empty">Select words in the article to start a thread, or write a thought below.</p>}
    {threads.map((thread) => <section key={thread.id} className="surf-passage-thread" data-thread={thread.id} data-active={active === thread.id || undefined}>
      <div className="surf-thread-context" data-thread-anchor={thread.source?.quote ? passageKey(thread.source) : undefined}>
        {thread.source ? <button type="button" onClick={() => onSelect(thread)}>
          <span>{thread.source.label} · {thread.messages.length} {thread.messages.length === 1 ? 'thought' : 'thoughts'} · Read in source ↗</span>
          {thread.source.quote && <q>{thread.source.quote}</q>}
        </button> : <span className="surf-thread-general">Room thought · {thread.messages.length} {thread.messages.length === 1 ? 'contribution' : 'contributions'}</span>}
      </div>
      {thread.roots.map((root) => branch(root, 0, new Set()))}
    </section>)}
  </div>
}
