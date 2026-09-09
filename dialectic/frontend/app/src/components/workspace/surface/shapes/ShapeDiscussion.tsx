import { useEffect, useMemo, useRef, useState } from 'react'
import type { MessageRef } from '../../../../types'
import type { MessageListProps } from '../../../chat/MessageList'
import type { InvestigateMode } from '../../../chat/MessageBubble'
import { SurfaceMessage } from './SurfaceMessage'
import { clusterDiscussionMap, discussionMap, focusDiscussionMap, searchDiscussionMap, passageKey, type DiscussionMapNode, type DiscussionThread, type SurfaceMsg } from '../surfaceModel'
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
  onInvestigate?: (id: string, quote?: string, mode?: InvestigateMode) => void
  onJump: (id: string) => void
}

/** Compact branches and the map navigate the same persisted quotations and replies. */
export function ShapeDiscussion({ threads, controls, selected, active, jump, map, mapExpanded, onToggleMap, onSelect, onOpenRef, onReply, onInvestigate, onJump }: Props) {
  const onSeen = controls.onSeen
  const rootRef = useRef<HTMLDivElement>(null)
  const lastSeen = useRef(-1)
  const lastJump = useRef<number | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [expandedPassages, setExpandedPassages] = useState<Set<string>>(new Set())
  const [zoom, setZoom] = useState(1)
  const [mapQuery, setMapQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [compactPanel, setCompactPanel] = useState<'search' | 'context' | 'controls' | null>(null)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [mapCollapsed, setMapCollapsed] = useState<Set<string>>(new Set())
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set())
  const mapRef = useRef<HTMLDivElement>(null)
  const mapPosition = useRef({ left: 0, top: 0 })
  const pendingFit = useRef(false)
  const drag = useRef<{ id: number; x: number; y: number; left: number; top: number } | null>(null)
  const graph = useMemo(() => discussionMap(threads, selected), [threads, selected])
  // Overview scale (50% and below) folds large branches; a focused path never folds.
  const overview = !focusId && Math.round(zoom * 100) <= 50
  const visibleGraph = useMemo(() => {
    const focused = focusDiscussionMap(graph, focusId, mapCollapsed)
    return overview ? clusterDiscussionMap(focused, expandedClusters) : focused
  }, [graph, focusId, mapCollapsed, overview, expandedClusters])
  const clusterCount = visibleGraph.nodes.filter((node) => node.kind === 'cluster').length
  const matches = useMemo(() => searchDiscussionMap(graph, mapQuery), [graph, mapQuery])
  const focusedNode = graph.nodes.find((node) => node.id === focusId)
  const layout = useMemo(() => {
    const byId = new Map(visibleGraph.nodes.map((node) => [node.id, node]))
    const nodes: (DiscussionMapNode & { x: number; y: number })[] = []
    let row = 0
    const placed = new Set<string>()
    const place = (node: DiscussionMapNode, depth: number): void => {
      if (placed.has(node.id)) return
      placed.add(node.id)
      nodes.push({ ...node, x: 540 + depth * 270, y: row++ * 128 })
      for (const edge of visibleGraph.edges) if (edge.from === node.id && edge.kind === 'reply') place(byId.get(edge.to)!, depth + 1)
    }
    for (const node of visibleGraph.nodes) if (node.kind === 'thought' && !visibleGraph.edges.some((edge) => edge.to === node.id && edge.kind === 'reply')) place(node, 0)
    for (const node of visibleGraph.nodes) if (node.kind === 'thought') place(node, 0)
    for (const kind of ['source', 'passage'] as const) {
      let sourceRow = 0
      for (const node of visibleGraph.nodes) if (node.kind === kind) nodes.push({ ...node, x: kind === 'source' ? 0 : 270, y: sourceRow++ * 128 })
    }
    // A free-standing human thought does not reserve two empty source columns.
    const left = nodes.length ? Math.min(...nodes.map((node) => node.x)) : 0
    for (const node of nodes) node.x -= left
    return { nodes, width: Math.max(240, ...nodes.map((node) => node.x + 240)), height: Math.max(116, ...nodes.map((node) => node.y + 116)) }
  }, [visibleGraph])

  function fitMap(): void {
    const pane = mapRef.current
    if (!pane?.clientWidth || !pane.clientHeight) return
    setZoom(Math.min(1, Math.max(1, pane.clientWidth - 24) / layout.width, Math.max(1, pane.clientHeight - 24) / layout.height))
    pane.scrollLeft = 0
    pane.scrollTop = 0
    mapPosition.current = { left: 0, top: 0 }
  }

  function changeZoom(value: number): void {
    const next = Math.max(.15, Math.min(1.8, value))
    const pane = mapRef.current
    const center = pane ? { left: (pane.scrollLeft + pane.clientWidth / 2) / zoom, top: (pane.scrollTop + pane.clientHeight / 2) / zoom } : null
    setZoom(next)
    requestAnimationFrame(() => {
      if (!pane || !center) return
      pane.scrollLeft = Math.max(0, center.left * next - pane.clientWidth / 2)
      pane.scrollTop = Math.max(0, center.top * next - pane.clientHeight / 2)
      mapPosition.current = { left: pane.scrollLeft, top: pane.scrollTop }
    })
  }

  function focusNode(id: string): void {
    setCompactPanel(null)
    if (id === focusId) { setSearchOpen(false); return }
    pendingFit.current = true
    setFocusId(id)
    setSearchOpen(false)
  }

  function selectSearchResult(id: string): void {
    focusNode(id)
    // The compact search hides on selection; focus its newly visible map.
    requestAnimationFrame(() => mapRef.current?.focus({ preventScroll: true }))
  }

  function showWholeMap(): void {
    pendingFit.current = true
    setFocusId(null)
    setMapCollapsed(new Set())
    setExpandedClusters(new Set())
    setSearchOpen(false)
    setCompactPanel(null)
  }

  function expandCluster(node: DiscussionMapNode): void {
    if (node.cluster) setExpandedClusters((current) => new Set([...current, node.cluster!.parentId]))
  }

  function toggleCompactPanel(panel: 'search' | 'context' | 'controls'): void {
    setCompactPanel((current) => current === panel ? null : panel)
    if (panel === 'search' && compactPanel !== 'search') requestAnimationFrame(() => {
      mapRef.current?.parentElement?.querySelector<HTMLInputElement>('.surf-map-search input')?.focus({ preventScroll: true })
    })
  }

  function openMapNode(node: DiscussionMapNode): void {
    if (node.kind === 'cluster') expandCluster(node)
    else if (node.kind === 'thought') onJump(node.id)
    else if (node.kind === 'passage' && node.threadId) {
      const thread = threads.find((candidate) => candidate.id === node.threadId)
      if (thread) onSelect(thread)
    } else if (node.ref) onOpenRef(node.ref, node.message?.id)
  }

  useEffect(() => {
    if (!map) return
    const frame = requestAnimationFrame(() => {
      const pane = mapRef.current
      if (pane) { pane.scrollLeft = mapPosition.current.left; pane.scrollTop = mapPosition.current.top }
    })
    return () => cancelAnimationFrame(frame)
  }, [map])

  useEffect(() => {
    if (!map || !pendingFit.current) return
    let scrollFrame: number | undefined
    const frame = requestAnimationFrame(() => {
      const pane = mapRef.current
      if (!pane?.clientWidth || !pane.clientHeight) return
      const next = 1
      setZoom(next)
      const target = layout.nodes.find((node) => node.id === focusId)
      const position = target ? { left: Math.max(0, (target.x + 120) * next - pane.clientWidth / 2), top: Math.max(0, (target.y + 58) * next - pane.clientHeight / 2) } : { left: 0, top: 0 }
      scrollFrame = requestAnimationFrame(() => {
        pane.scrollLeft = position.left
        pane.scrollTop = position.top
        mapPosition.current = { left: pane.scrollLeft, top: pane.scrollTop }
        // A token can change layout between frames. Consume the request only
        // after positioning, so cancellation retries against the current graph.
        pendingFit.current = false
      })
    })
    return () => {
      cancelAnimationFrame(frame)
      if (scrollFrame !== undefined) cancelAnimationFrame(scrollFrame)
    }
  }, [map, layout, focusId])
  const messages = useMemo(() => threads.flatMap((thread) => thread.messages), [threads])
  const children = useMemo(() => {
    const result = new Map<string, SurfaceMsg[]>()
    for (const message of messages) if (message.parentId) {
      result.set(message.parentId, [...(result.get(message.parentId) ?? []), message])
    }
    return result
  }, [messages])
  useEffect(() => {
    if (!jump || map || lastJump.current === jump.nonce) return
    let target = messages.find((message) => message.id === jump.id)
    // A receipt can arrive before React renders the accepted message.
    if (!target) return
    const parents = new Set<string>()
    while (target?.parentId && !parents.has(target.parentId)) {
      parents.add(target.parentId)
      target = messages.find((message) => message.id === target!.parentId)
    }
    const frame = requestAnimationFrame(() => {
      if ([...parents].some((id) => collapsed.has(id))) {
        setCollapsed((current) => new Set([...current].filter((id) => !parents.has(id))))
        return
      }
      const root = rootRef.current
      const node = [...(root?.querySelectorAll<HTMLElement>('[data-mid]') ?? [])].find((candidate) => candidate.dataset.mid === jump.id)
      if (!node || !root) return
      // Only this pane moves. Consume the receipt once so peer arrivals leave reading position alone.
      root.scrollTop += node.getBoundingClientRect().top - root.getBoundingClientRect().top - 90
      lastJump.current = jump.nonce
    })
    return () => cancelAnimationFrame(frame)
  }, [jump, map, messages, collapsed])

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

  /** Reply depth is the DOM nesting (`data-depth`); the visible indent and shade
   *  follow FORK depth only. A one-reply chain (a summons and its answer, and
   *  the next) reads at full width; a real disagreement opens a shaded rail. */
  function branch(message: SurfaceMsg, depth: number, ancestors: Set<string>, forkDepth = 0, fork = false): React.ReactNode {
    if (ancestors.has(message.id)) return null
    const descendants = children.get(message.id) ?? []
    const closed = collapsed.has(message.id)
    const forks = descendants.length > 1
    return <div className="surf-branch" key={message.id} data-depth={depth} data-fork={fork || undefined} style={{ '--fork-depth': forkDepth } as React.CSSProperties}>
      <SurfaceMessage msg={message} compact controls={{ ...controls, contextRef: selected }} onReply={onReply} onInvestigate={onInvestigate} onOpenRef={(ref) => onOpenRef(ref, message.id)} threadSource={threads.find((thread) => thread.messages.some((item) => item.id === message.id))?.source ?? null} />
      {descendants.length > 0 && <button type="button" className="surf-branch-toggle" aria-expanded={!closed}
        onClick={() => setCollapsed((current) => { const next = new Set(current); if (closed) next.delete(message.id); else next.add(message.id); return next })}>
        {closed ? '+' : '−'} {descendants.length} {descendants.length === 1 ? 'reply' : 'replies'} to {message.author.name}
      </button>}
      {!closed && descendants.map((child) => branch(child, depth + 1, new Set([...ancestors, message.id]), forkDepth + (forks ? 1 : 0), forks))}
    </div>
  }

  if (map) {
    const byId = new Map(layout.nodes.map((node) => [node.id, node]))
    const descendantCount = (id: string): number => {
      const descendants = new Set<string>()
      const visit = (parent: string): void => {
        for (const edge of graph.edges) if (edge.kind === 'reply' && edge.from === parent && !descendants.has(edge.to)) {
          descendants.add(edge.to)
          visit(edge.to)
        }
      }
      visit(id)
      return descendants.size
    }
    return <div className="surf-discussion surf-mindmap" data-compact-panel={compactPanel ?? undefined} onKeyDown={(event) => {
      if (event.key === 'Escape' && compactPanel) {
        event.currentTarget.querySelector<HTMLButtonElement>('.surf-map-compactbar button[aria-expanded="true"]')?.focus({ preventScroll: true })
        setCompactPanel(null)
      }
    }}>
      <div className="surf-map-compactbar">
        <button type="button" aria-label="Search map" aria-expanded={compactPanel === 'search'} onClick={() => toggleCompactPanel('search')}>Search</button>
        <button type="button" aria-label="Show selected map context" disabled={!focusedNode} aria-expanded={compactPanel === 'context'} onClick={() => toggleCompactPanel('context')}>Context</button>
        <button type="button" aria-label="Map controls" aria-expanded={compactPanel === 'controls'} onClick={() => toggleCompactPanel('controls')}>Controls</button>
        <button type="button" aria-label="Show complete map" disabled={!focusId && mapCollapsed.size === 0 && expandedClusters.size === 0} onClick={showWholeMap}>Whole map</button>
        <button type="button" aria-label="Fit compact map" onClick={() => { setCompactPanel(null); fitMap() }}>Fit</button>
      </div>
      <div className="surf-map-controls">
      <div className="surf-map-search">
        <input type="search" aria-label="Search map by person, phrase, source or passage" placeholder="Find a person, phrase or passage…" value={mapQuery}
          onFocus={() => setSearchOpen(true)} onChange={(event) => { setMapQuery(event.target.value); setSearchOpen(true) }}
          onKeyDown={(event) => { if (event.key === 'Escape') setSearchOpen(false); if (event.key === 'Enter' && matches[0]) selectSearchResult(matches[0].id) }} />
        {mapQuery && <button type="button" aria-label="Clear search" onClick={() => { setMapQuery(''); setSearchOpen(false) }}>×</button>}
        <button type="button" disabled={!focusId && mapCollapsed.size === 0 && expandedClusters.size === 0} onClick={showWholeMap}>Show whole map</button>
      </div>
      {mapQuery.trim() && searchOpen && <div className="surf-map-results" aria-label="Map search results">
        <p role="status">{matches.length} {matches.length === 1 ? 'match' : 'matches'} in loaded discussion</p>
        {matches.map((node) => <button type="button" key={node.id} onClick={() => selectSearchResult(node.id)}><b>{node.kind === 'passage' ? 'Passage · ' : ''}{node.label}</b>{' '}<span>{node.text}</span></button>)}
      </div>}
      <div className="surf-map-tools">
        {onToggleMap && <button type="button" onClick={onToggleMap}>{mapExpanded ? 'Open article' : 'Expand map'}</button>}
        <span>{focusedNode ? 'Focused path' : `${layout.nodes.filter((node) => node.kind === 'thought').length} thoughts`} · {graph.edges.filter((edge) => edge.kind === 'reply').length} replies{clusterCount > 0 && ` · ${clusterCount} folded ${clusterCount === 1 ? 'branch' : 'branches'}`}</span>
        <button type="button" onClick={fitMap}>Fit view</button>
        <button type="button" aria-label="Zoom out map" disabled={zoom <= .15} onClick={() => changeZoom(zoom - .1)}>−</button>
        <button type="button" aria-label="Reset map zoom" onClick={() => changeZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button type="button" aria-label="Zoom in map" disabled={zoom >= 1.8} onClick={() => changeZoom(zoom + .1)}>+</button>
      </div>
      </div>
      {focusedNode && <div className="surf-map-focus-context" key={focusedNode.id} aria-label="Selected map context">
        <div><b>{focusedNode.label}</b><button type="button" onClick={() => openMapNode(focusedNode)}>{focusedNode.kind === 'thought' ? 'Open in thread ↗' : 'Read in source ↗'}</button></div>
        <p tabIndex={0} aria-label="Selected context text">{focusedNode.text}</p>
      </div>}
      <div className="surf-map-scroll" ref={mapRef} tabIndex={0} aria-label="Mind map; drag or scroll to explore. Arrow keys pan, plus and minus zoom, zero fits the map."
        onScroll={(event) => { mapPosition.current = { left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop } }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return
          const pane = event.currentTarget
          if (['+', '=', '-', '0', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) event.preventDefault()
          if (event.key === '+' || event.key === '=') changeZoom(zoom + .1)
          if (event.key === '-') changeZoom(zoom - .1)
          if (event.key === '0') fitMap()
          if (event.key === 'ArrowLeft') pane.scrollLeft -= 120
          if (event.key === 'ArrowRight') pane.scrollLeft += 120
          if (event.key === 'ArrowUp') pane.scrollTop -= 120
          if (event.key === 'ArrowDown') pane.scrollTop += 120
        }}
        onPointerDown={(event) => {
          if (event.pointerType !== 'mouse' || event.button !== 0 || (event.target as HTMLElement).closest('button, input, summary')) return
          const pane = event.currentTarget
          drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: pane.scrollLeft, top: pane.scrollTop }
          pane.setPointerCapture(event.pointerId)
          pane.focus({ preventScroll: true })
          event.preventDefault()
        }}
        onPointerMove={(event) => {
          if (!drag.current || drag.current.id !== event.pointerId) return
          event.currentTarget.scrollLeft = drag.current.left - (event.clientX - drag.current.x)
          event.currentTarget.scrollTop = drag.current.top - (event.clientY - drag.current.y)
        }}
        onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}>
        <div style={{ width: layout.width * zoom, height: layout.height * zoom }}>
          <div className="surf-map-canvas" style={{ width: layout.width, height: layout.height, transform: `scale(${zoom})` }}>
            <svg width={layout.width} height={layout.height} aria-hidden="true">{visibleGraph.edges.map((edge, i) => {
              const from = byId.get(edge.from), to = byId.get(edge.to)
              if (!from || !to) return null
              return <path key={i} data-kind={edge.kind} d={`M${from.x + 240},${from.y + 48} C${from.x + 260},${from.y + 48} ${to.x - 20},${to.y + 48} ${to.x},${to.y + 48}`}><title>{edge.kind}</title></path>
            })}</svg>
            {layout.nodes.map((node) => {
              const replies = node.kind === 'thought' ? descendantCount(node.id) : 0
              if (node.kind === 'cluster') return <div key={node.id} data-map-id={node.id} className="surf-map-node surf-map-node--cluster" style={{ left: node.x, top: node.y }}>
                <button type="button" className="surf-map-node-open" aria-label={`Expand ${node.label}`} onClick={() => expandCluster(node)}><b>{node.label}</b>{' '}<span>{node.text}</span></button>
                <div className="surf-map-node-actions">
                  <button type="button" onClick={() => expandCluster(node)}>Expand</button>
                  <button type="button" aria-label={`Focus path for ${node.label}`} onClick={() => focusNode(node.cluster!.parentId)}>Focus path</button>
                </div>
              </div>
              return <div key={node.id} data-map-id={node.id} data-focused={node.id === focusId || undefined} className={`surf-map-node surf-map-node--${node.kind}`} style={{ left: node.x, top: node.y }}>
                <button type="button" className="surf-map-node-open" onClick={() => openMapNode(node)}><b>{node.kind === 'passage' ? 'Passage · ' : ''}{node.label}</b>{' '}<span>{node.text || 'Open contribution'}</span></button>
                <div className="surf-map-node-actions">
                  <button type="button" aria-label={`Focus path for ${node.label}: ${node.text.slice(0, 60)}`} aria-pressed={node.id === focusId} onClick={() => focusNode(node.id)}>Focus path</button>
                  {replies > 0 && !focusId && <button type="button" aria-expanded={!mapCollapsed.has(node.id)} aria-label={`${mapCollapsed.has(node.id) ? 'Show' : 'Hide'} ${replies} replies to ${node.label}`} onClick={() => setMapCollapsed((current) => {
                    const next = new Set(current); if (next.has(node.id)) next.delete(node.id); else next.add(node.id); return next
                  })}>{mapCollapsed.has(node.id) ? '+' : '−'} {replies} {replies === 1 ? 'reply' : 'replies'}</button>}
                </div>
              </div>
            })}
          </div>
        </div>
        {layout.nodes.length === 0 && <p>Select a source or start a thought. The map grows from your discussion.</p>}
      </div>
    </div>
  }
  return <div ref={rootRef} className="surf-discussion" aria-label="Passage discussion threads">
    {threads.length === 0 && <p className="surf-conv-empty">Select words in the article to start a thread, or write a thought below.</p>}
    {threads.map((thread) => <section key={thread.id} className="surf-passage-thread" data-thread={thread.id} data-active={active === thread.id || undefined}>
      <div className="surf-thread-context" data-thread-anchor={thread.source?.quote ? passageKey(thread.source) : undefined}>
        {thread.source ? <button type="button" onClick={() => onSelect(thread)}>
          <span>{thread.source.label} · {thread.messages.length} {thread.messages.length === 1 ? 'thought' : 'thoughts'} · Read in source ↗</span>
          {thread.source.quote && <q data-expanded={expandedPassages.has(thread.id) || undefined}>{thread.source.quote}</q>}
        </button> : <span className="surf-thread-general">Room thought · {thread.messages.length} {thread.messages.length === 1 ? 'contribution' : 'contributions'}</span>}
        {thread.source?.quote && thread.source.quote.length > 300 && <button type="button" className="surf-quote-toggle" aria-expanded={expandedPassages.has(thread.id)} onClick={() => setExpandedPassages((current) => {
          const next = new Set(current); if (next.has(thread.id)) next.delete(thread.id); else next.add(thread.id); return next
        })}>{expandedPassages.has(thread.id) ? 'Collapse passage' : 'Expand passage'}</button>}
      </div>
      {thread.roots.map((root) => branch(root, 0, new Set()))}
    </section>)}
  </div>
}
