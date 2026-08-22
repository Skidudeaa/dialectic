import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Explain } from './Explain'
import { GLOSSARY } from '../../lib/glossary'

// These fence three things, in descending order of how expensive the failure
// is: that an undefined term degrades to plain prose instead of a marker
// pointing at nothing; that the disclosure is operable and dismissible without
// a mouse; and that the panel keeps the remedy PassageMarker.tsx paid for in
// browser acceptance — viewport coordinates under position:fixed.

/** jsdom's default viewport. Both clamp bounds are read against these. */
const VIEW_W = 1024
const VIEW_H = 768

function rect(over: Partial<DOMRect>): DOMRect {
  return {
    top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0,
    toJSON: () => ({}), ...over,
  } as DOMRect
}

/** Give the trigger and the panel their own boxes — jsdom measures nothing. */
function stubRects(trigger: Partial<DOMRect>, panel: Partial<DOMRect> = {}) {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      return rect(this.classList.contains('explain-panel') ? panel : trigger)
    },
  )
}

describe('Explain', () => {
  it('renders the label it wraps, as a button', () => {
    render(<Explain term="brier">Brier score</Explain>)
    expect(screen.getByRole('button', { name: 'Brier score' })).toBeInTheDocument()
  })

  it('opens on click and puts the short definition in the document', () => {
    render(<Explain term="brier">Brier score</Explain>)
    const trigger = screen.getByRole('button', { name: 'Brier score' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(trigger)

    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(GLOSSARY.brier.short)).toBeInTheDocument()
    // A role and an accessible name, so it is reachable rather than merely painted.
    expect(screen.getByRole('note', { name: /Brier score/ })).toBeInTheDocument()
  })

  it('closes on Escape and hands focus back to the trigger', () => {
    render(<Explain term="brier">Brier score</Explain>)
    const trigger = screen.getByRole('button', { name: 'Brier score' })
    fireEvent.click(trigger)
    expect(screen.getByRole('note')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(trigger).toHaveFocus()
  })

  it('closes on a click outside', () => {
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))
    expect(screen.getByRole('note')).toBeInTheDocument()

    fireEvent.mouseDown(document.body)

    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('closes on scroll — it is pinned to the viewport, the words are not', () => {
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))
    expect(screen.getByRole('note')).toBeInTheDocument()

    fireEvent.scroll(document, {})

    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('names the bare marker, which has no visible label of its own', () => {
    render(<Explain term="brier" />)
    fireEvent.click(screen.getByRole('button', { name: 'What Brier score means' }))
    expect(screen.getByText(GLOSSARY.brier.short)).toBeInTheDocument()
  })

  it('has no dangling see-also — a chip that resolves to nothing renders nothing', () => {
    // The one silent failure mode in the data file: a mistyped key leaves the
    // "See also" label standing with no chips beside it, which looks like a
    // rendering bug and is a typo.
    const dangling = Object.entries(GLOSSARY).flatMap(([key, entry]) =>
      (entry.seeAlso ?? [])
        .filter((related) => !(related in GLOSSARY))
        .map((related) => `${key} → ${related}`),
    )
    expect(dangling).toEqual([])
  })

  it('renders children and NO button for a term the glossary does not define', () => {
    render(<Explain term="not-a-real-term">Some label</Explain>)
    expect(screen.getByText('Some label')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('follows a see-also into the related entry, in the same panel', () => {
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))

    fireEvent.click(screen.getByRole('button', { name: 'Coverage' }))

    expect(screen.getByText(GLOSSARY.coverage.short)).toBeInTheDocument()
    expect(screen.queryByText(GLOSSARY.brier.short)).not.toBeInTheDocument()
  })

  // ── the positioning scar ────────────────────────────────────────────────
  // PassageMarker.tsx shipped an un-clickable menu because position:absolute
  // trapped it in `.msg`'s stacking context, where a later message's byline
  // painted over it. The remedy was viewport coordinates under position:fixed
  // plus dismissal on scroll. All three are asserted here.

  it('places the panel at VIEWPORT coordinates read off the trigger', () => {
    stubRects({ top: 180, bottom: 200, left: 40 })
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))

    const panel = screen.getByRole('note')
    // trigger.bottom + the 6px gap, and the trigger's own left edge.
    expect(panel).toHaveStyle({ top: '206px', left: '40px' })
  })

  it('clamps a panel that would render past the right edge', () => {
    stubRects({ top: 100, bottom: 120, left: 900 }, { width: 320, height: 120 })
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))

    expect(screen.getByRole('note')).toHaveStyle({ left: `${VIEW_W - 320 - 8}px` })
  })

  it('flips above the trigger rather than rendering below the fold', () => {
    stubRects({ top: 700, bottom: 720, left: 40 }, { width: 320, height: 200 })
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))

    // Below would be 726 + 200 = 926, past the 768 viewport. Above is
    // 700 - 200 - 6 = 494, which fits.
    const panel = screen.getByRole('note')
    expect(panel).toHaveStyle({ top: '494px' })
    expect(Number.parseInt((panel as HTMLElement).style.top, 10) + 200)
      .toBeLessThanOrEqual(VIEW_H)
  })

  it('positions the panel FIXED — the coordinates above mean nothing otherwise', () => {
    // The scheme is set inline beside top/left rather than in the stylesheet,
    // precisely so this can be a real computed-style assertion. Vitest injects
    // no CSS into jsdom, so a rule living in Explain.css would only be
    // assertable by regex over the file — and a regex cannot tell a
    // declaration from a comment quoting one, in either direction.
    stubRects({ top: 180, bottom: 200, left: 40 })
    render(<Explain term="brier">Brier score</Explain>)
    fireEvent.click(screen.getByRole('button', { name: 'Brier score' }))

    expect(screen.getByRole('note')).toHaveStyle({ position: 'fixed' })
  })
})
