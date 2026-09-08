import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../lib/api'
import { anchorField, anchorFromSelection, readingAnchorFromSelection, MAX_QUOTE_CHARS, type PassageAnchor } from '../../lib/passageAnchor'
import './PassageMarker.css'

/**
 * Select a passage of a message, say what it is.
 *
 * WHY only single-subject relations here: `supports` and `challenges` need a
 * SECOND subject — this passage supports THAT one — which is a target-picking
 * flow, not a highlighter. Offering them with nothing to point at would
 * produce marks that assert a relation to nobody. They belong to the same
 * Field vocabulary and can join this menu the day there is a way to pick the
 * other end.
 */
const PASSAGE_RELATIONS: { relation: string; label: string; hint: string }[] = [
  { relation: 'emerging_position', label: 'Position', hint: 'A stance the room is forming' },
  { relation: 'evidence_attachment', label: 'Evidence', hint: 'Something this rests on' },
  { relation: 'unanswered_question', label: 'Question', hint: 'Asked, not yet answered' },
  { relation: 'possible_contradiction', label: 'Tension', hint: 'This sits badly with something else' },
]

interface PassageMarkerProps {
  roomId: string
  threadId: string
  messageId: string
  /** The rendered message body — selections outside it are ignored. */
  containerRef: React.RefObject<HTMLDivElement | null>
  /** Told when a mark lands, so the transcript can show it without a refetch. */
  onMarked?: () => void
  onInvestigate?: (quote: string) => void
}

export function PassageMarker({
  roomId, threadId, messageId, containerRef, onMarked, onInvestigate,
}: PassageMarkerProps) {
  const [anchor, setAnchor] = useState<PassageAnchor | null>(null)
  const [position, setPosition] = useState<{ top: number; left: number; maxWidth: number } | null>(null)
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle')
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    function readSelection() {
      const el = containerRef.current
      if (!el) return
      const selection = window.getSelection()
      const next = onInvestigate ? readingAnchorFromSelection(selection, el) : anchorFromSelection(selection, el)
      if (!next) {
        setAnchor(null)
        setPosition(null)
        return
      }
      const rect = selection!.getRangeAt(0).getBoundingClientRect()
      setAnchor(next)
      const pane = el.closest('.surf-discussion')?.getBoundingClientRect()
      const left = Math.max(8, pane?.left ?? 0)
      const right = Math.min(window.innerWidth - 8, pane?.right ?? window.innerWidth)
      const maxWidth = Math.min(440, right - left)
      const top = Math.max(8, pane?.top ?? 0)
      const bottom = Math.min(window.innerHeight - 8, pane?.bottom ?? window.innerHeight)
      setPosition({ top: Math.max(top, Math.min(bottom - 76, rect.top - 74)), left: Math.max(left, Math.min(right - maxWidth, rect.left)), maxWidth })
      setState('idle')
    }

    let frame = 0
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(readSelection) }
    document.addEventListener('selectionchange', schedule)
    container.addEventListener('pointerup', readSelection)
    container.addEventListener('keyup', readSelection)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('selectionchange', schedule)
      container.removeEventListener('pointerup', readSelection)
      container.removeEventListener('keyup', readSelection)
    }
  }, [containerRef, onInvestigate])

  // Any click elsewhere dismisses — including one that starts a new selection.
  useEffect(() => {
    if (!anchor) return
    function onDown(event: MouseEvent) {
      if (menuRef.current?.contains(event.target as Node)) return
      setAnchor(null)
      setPosition(null)
    }
    function onScroll() {
      // Fixed to the viewport, so a scroll would leave it pointing at words
      // that have moved. Dismiss rather than chase.
      setAnchor(null)
      setPosition(null)
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [anchor])

  async function mark(relation: string) {
    if (!anchor) return
    setState('saving')
    try {
      await api.createFieldMark(roomId, {
        relation,
        subjects: [{ entity: 'messages', id: messageId, field: anchorField(anchor) }],
        // The quote IS the title: a mark whose subject is a passage should
        // read as that passage, not as a row id.
        title: anchor.quote,
        payload: { quote: anchor.quote, occurrence: anchor.occurrence },
        thread_id: threadId,
      })
      window.getSelection()?.removeAllRanges()
      setAnchor(null)
      setPosition(null)
      setState('idle')
      onMarked?.()
    } catch {
      // Never lose the human's selection to a failure — they can retry, and
      // the anchor is still on screen to retry FROM.
      setState('error')
    }
  }

  if (!anchor || !position) return null

  return createPortal(
    <div
      ref={menuRef}
      className="passage-marker"
      style={{ top: position.top, left: position.left, maxWidth: position.maxWidth }}
      onPointerDown={(event) => event.preventDefault()}
      role="menu"
      aria-label="Mark this passage"
    >
      {onInvestigate && <button type="button" role="menuitem" className="passage-marker-btn" onClick={() => {
        onInvestigate(anchor.quote)
        window.getSelection()?.removeAllRanges()
        setAnchor(null)
        setPosition(null)
      }}>Find and pull</button>}
      {state === 'error' && (
        <span className="passage-marker-error" role="status">Could not mark — try again</span>
      )}
      {PASSAGE_RELATIONS.map((option) => (
        <button
          key={option.relation}
          type="button"
          role="menuitem"
          title={option.hint}
          disabled={state === 'saving' || anchor.quote.length > MAX_QUOTE_CHARS}
          className="passage-marker-btn"
          onClick={() => mark(option.relation)}
        >
          {option.label}
        </button>
      ))}
    </div>, document.body,
  )
}
