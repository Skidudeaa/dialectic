import { useEffect, useMemo, useRef, useState } from 'react'
import type { MessageAnchor, MessageRef } from '../../../../types'
import { refGlyph, refKindLabel, type SurfaceMsg } from '../surfaceModel'
import { SurfaceMessage } from './SurfaceMessage'
import './shapes.css'

export interface ShapeStreamProps {
  messages: SurfaceMsg[]
  onOpenRef: (ref: MessageRef) => void
  onReply?: (id: string) => void
  onAnchor?: (anchor: MessageAnchor) => void
}

/** Stay pinned to the tail only when the reader was already this close to it. */
const FOLLOW_THRESHOLD_PX = 120

/**
 * The plain chronological shape: a scrolling stream of messages beside a
 * context rail naming what the messages currently on screen are ABOUT — the
 * surface's answer to "what is this conversation touching right now".
 */
export function ShapeStream({ messages, onOpenRef, onReply, onAnchor }: ShapeStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  // Whether the reader was near the bottom the last time they scrolled — a
  // ref, not state: reading it must never itself trigger a render.
  const followRef = useRef(true)
  const [inView, setInView] = useState<Set<string>>(() => new Set())

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    followRef.current = distance <= FOLLOW_THRESHOLD_PX
  }

  const lastId = messages.length > 0 ? messages[messages.length - 1].id : null

  // Auto-scroll only when the tail actually moved, and only if the reader
  // was following it. jsdom reports scrollHeight 0 (no layout engine), so
  // this is a harmless no-op in tests.
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !followRef.current) return
    el.scrollTop = el.scrollHeight
  }, [lastId])

  // IntersectionObserver over the rows, keyed by the wrapper's own data-mid
  // (not SurfaceMessage's inner one — .surf-row is the unique, single
  // target per message). Guarded: jsdom does not implement it.
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const root = scrollRef.current
    if (!root) return
    const observer = new IntersectionObserver(
      (entries) => {
        setInView((prev) => {
          const next = new Set(prev)
          for (const entry of entries) {
            const id = (entry.target as HTMLElement).dataset.mid
            if (!id) continue
            if (entry.isIntersecting) next.add(id)
            else next.delete(id)
          }
          return next
        })
      },
      { root, threshold: 0.15 },
    )
    const rows = root.querySelectorAll('.surf-row[data-mid]')
    rows.forEach((row) => observer.observe(row))
    return () => observer.disconnect()
  }, [messages])

  // Rail content is derived from the messages themselves (in their own
  // order) rather than from observer callback order, which is not
  // deterministic render-to-render — "first appearance" means first in the
  // stream, not first to fire.
  const railRefs = useMemo(() => {
    const seen = new Set<string>()
    const out: MessageRef[] = []
    for (const m of messages) {
      if (!inView.has(m.id)) continue
      for (const ref of m.refs) {
        const key = `${ref.entity}:${ref.id}`
        if (seen.has(key)) continue
        seen.add(key)
        out.push(ref)
      }
    }
    return out
  }, [messages, inView])

  return (
    <div className="surf-stream">
      <div className="surf-stream-scroll" ref={scrollRef} onScroll={handleScroll}>
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`surf-row${inView.has(msg.id) ? ' is-inview' : ''}`}
            data-mid={msg.id}
          >
            <SurfaceMessage msg={msg} onOpenRef={onOpenRef} onReply={onReply} onAnchor={onAnchor} />
          </div>
        ))}
      </div>
      <aside className="surf-rail">
        <div className="surf-rail-header">CONTEXT RAIL · {inView.size} in view</div>
        {railRefs.length === 0 ? (
          <p className="surf-rail-empty">Nothing in view links to an object yet.</p>
        ) : (
          <ul className="surf-rail-list">
            {railRefs.map((ref) => (
              <li key={`${ref.entity}:${ref.id}`}>
                <button type="button" className="surf-rail-card" onClick={() => onOpenRef(ref)}>
                  <span className="surf-rail-glyph" aria-hidden="true">{refGlyph(ref.entity)}</span>
                  <span className="surf-rail-kind">{refKindLabel(ref.entity)}</span>
                  <span className="surf-rail-label">{ref.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}
