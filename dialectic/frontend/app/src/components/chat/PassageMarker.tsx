import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { anchorField, anchorFromSelection, type PassageAnchor } from '../../lib/passageAnchor'
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
}

export function PassageMarker({
  roomId, threadId, messageId, containerRef, onMarked,
}: PassageMarkerProps) {
  const [anchor, setAnchor] = useState<PassageAnchor | null>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle')
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    function readSelection() {
      const el = containerRef.current
      if (!el) return
      const selection = window.getSelection()
      const next = anchorFromSelection(selection, el)
      if (!next) {
        setAnchor(null)
        setPosition(null)
        return
      }
      const rect = selection!.getRangeAt(0).getBoundingClientRect()
      setAnchor(next)
      // VIEWPORT coordinates with position:fixed, not offsets inside the
      // message. Inside, the menu is trapped in `.msg`'s stacking context and
      // a LATER message's byline paints over it — z-index 30 loses to a
      // sibling at auto, because the contest is between the two `.msg`
      // elements, not between the menu and the byline. Browser acceptance
      // found it as an un-clickable button, which is what a reader would have
      // found too. Scrolling dismisses (below), so nothing drifts.
      setPosition({ top: rect.top - 38, left: rect.left })
      setState('idle')
    }

    // pointerup rather than selectionchange: the latter fires on every
    // character as a drag proceeds, which flickers the menu across the screen.
    container.addEventListener('pointerup', readSelection)
    container.addEventListener('keyup', readSelection)
    return () => {
      container.removeEventListener('pointerup', readSelection)
      container.removeEventListener('keyup', readSelection)
    }
  }, [containerRef])

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

  return (
    <div
      ref={menuRef}
      className="passage-marker"
      style={{ top: position.top, left: position.left }}
      role="menu"
      aria-label="Mark this passage"
    >
      {state === 'error' && (
        <span className="passage-marker-error" role="status">Could not mark — try again</span>
      )}
      {PASSAGE_RELATIONS.map((option) => (
        <button
          key={option.relation}
          type="button"
          role="menuitem"
          title={option.hint}
          disabled={state === 'saving'}
          className="passage-marker-btn"
          onClick={() => mark(option.relation)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
