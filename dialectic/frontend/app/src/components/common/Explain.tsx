import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { glossaryEntry } from '../../lib/glossary'
import './Explain.css'

/**
 * Inline definition for one hard word, on tap or on Enter.
 *
 *   <Explain term="brier" />                     a bare marker
 *   <Explain term="brier">Brier score</Explain>  the label itself becomes it
 *
 * WHY IT IS A BUTTON AND NOT A `title` TOOLTIP: sceneIdentity.ts states the
 * rule plainly — hover-only meaning is barred by the accessibility gate. A
 * `title` is invisible to touch, unreachable by keyboard, and unstyleable.
 * This is a disclosure: a real button carrying aria-expanded, dismissed by
 * Escape with focus handed back, by a click outside, and by a scroll.
 *
 * FAILS SOFT BY DESIGN: a term the glossary does not define renders its
 * children as plain text and NO button. A marker that opens nothing is worse
 * than no marker, and this is the shape that four call sites can adopt without
 * each one guarding its own key.
 *
 * THE POSITIONING SCAR — read PassageMarker.tsx before changing this. Its menu
 * shipped un-clickable because `position: absolute` trapped it in `.msg`'s
 * stacking context, where a LATER message's byline painted over it: z-index 30
 * loses to a sibling at auto, because the contest is between the two `.msg`
 * elements and not between the menu and the byline. Browser acceptance found
 * it, no unit test could have. So this panel uses the same remedy and the same
 * one only: VIEWPORT coordinates read from getBoundingClientRect() with
 * `position: fixed`, and dismissal on scroll registered with capture true —
 * fixed to the viewport, a scroll would otherwise leave it pointing at a word
 * that has moved. It is then clamped to the viewport, because the marker sits
 * in running text and a definition that renders past the right edge or below
 * the fold on a 390px phone is a definition nobody can read.
 */
export interface ExplainProps {
  /** A key in `lib/glossary.ts`. Unknown keys render children and no button. */
  term: string
  /** The label to wrap. Omit for a bare marker. */
  children?: React.ReactNode
  /** Extra class on the trigger, for call sites that need to sit it in a row. */
  className?: string
}

/** Keeps the panel off the very edge on a narrow screen. */
const VIEWPORT_MARGIN = 8
/** Gap between the trigger and the panel. */
const OFFSET = 6

export function Explain({ term, children, className }: ExplainProps) {
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const panelId = useId()

  const entry = glossaryEntry(term)
  const shown = activeKey ? glossaryEntry(activeKey) : null
  const open = Boolean(shown)

  // Escape closes and hands focus back; a click anywhere else closes; a scroll
  // closes, because the panel is pinned to the viewport and the words are not.
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      setActiveKey(null)
      triggerRef.current?.focus()
    }
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node
      if (panelRef.current?.contains(target)) return
      if (triggerRef.current?.contains(target)) return
      setActiveKey(null)
    }
    function onScroll(event: Event) {
      // A tall entry makes the panel scroll ITSELF (max-height in Explain.css).
      // This listener is registered in the CAPTURE phase, so that inner scroll
      // reaches it too and would close the panel at the exact moment a reader
      // scrolled down to finish reading it. Only a scroll of something OUTSIDE
      // the panel means the word this is anchored to has moved.
      const target = event.target as Node | null
      if (target && panelRef.current?.contains(target)) return
      setActiveKey(null)
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

  // The placement React renders is a guess made without the panel's own size,
  // because nothing can measure a box before it exists. So measure it here and
  // pull it back inside the viewport BEFORE paint.
  //
  // WHY this writes the node instead of calling setPos: a second state pass
  // would be a cascading render, which `react-hooks/set-state-in-effect`
  // rightly refuses. Positioning a floating box against the real viewport is
  // the layout-effect's actual job — syncing React's output to a platform
  // measurement — so the correction belongs on the element.
  useLayoutEffect(() => {
    const panel = panelRef.current
    if (!pos || !panel) return
    const rect = panel.getBoundingClientRect()
    let { top, left } = pos
    if (left + rect.width > window.innerWidth - VIEWPORT_MARGIN) {
      left = window.innerWidth - rect.width - VIEWPORT_MARGIN
    }
    if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN
    if (top + rect.height > window.innerHeight - VIEWPORT_MARGIN) {
      // Flip above the trigger when there is room there; otherwise sit on the
      // bottom margin, which still beats being cut off by the fold.
      const trigger = triggerRef.current?.getBoundingClientRect()
      const above = (trigger ? trigger.top : top) - rect.height - OFFSET
      top = above >= VIEWPORT_MARGIN
        ? above
        : Math.max(VIEWPORT_MARGIN, window.innerHeight - rect.height - VIEWPORT_MARGIN)
    }
    panel.style.top = `${top}px`
    panel.style.left = `${left}px`
  }, [pos, activeKey])

  if (!entry) return <>{children}</>

  function toggle() {
    if (open) {
      setActiveKey(null)
      return
    }
    const rect = triggerRef.current?.getBoundingClientRect()
    setPos({ top: (rect?.bottom ?? 0) + OFFSET, left: rect?.left ?? 0 })
    setActiveKey(term.trim().toLowerCase())
  }

  const bare = children === undefined || children === null || children === false

  return (
    <span className="explain">
      <button
        ref={triggerRef}
        type="button"
        className={`explain-trigger${bare ? ' is-bare' : ''}${className ? ` ${className}` : ''}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        // The bare marker has no visible text to be named by. The wrapped form
        // is named by its own label, which is the point of wrapping it.
        aria-label={bare ? `What ${entry.term} means` : undefined}
        onClick={toggle}
      >
        {bare ? <span aria-hidden="true">?</span> : children}
      </button>
      {shown && pos && (
        <div
          ref={panelRef}
          id={panelId}
          className="explain-panel"
          // `position` is inline BESIDE the coordinates deliberately, not in
          // the stylesheet: top/left here are viewport numbers off
          // getBoundingClientRect(), and they mean something else entirely
          // under any other positioning scheme. Keeping the scheme with the
          // numbers is what makes the scar guard in Explain.test.tsx a real
          // assertion rather than a regex over prose.
          style={{ position: 'fixed', top: pos.top, left: pos.left }}
          role="note"
          aria-label={`${shown.term} — what it means`}
        >
          <p className="explain-term">{shown.term}</p>
          <p className="explain-short">{shown.short}</p>
          {shown.long && <p className="explain-long">{shown.long}</p>}
          {shown.seeAlso && shown.seeAlso.length > 0 && (
            <p className="explain-see">
              <span className="explain-see-label">See also</span>
              {shown.seeAlso.map((key) => {
                const related = glossaryEntry(key)
                if (!related) return null
                return (
                  <button
                    key={key}
                    type="button"
                    className="explain-see-btn"
                    onClick={() => setActiveKey(key)}
                  >
                    {related.term}
                  </button>
                )
              })}
            </p>
          )}
        </div>
      )}
    </span>
  )
}
