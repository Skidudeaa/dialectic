import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LibraryScene } from './LibraryScene'
import { LedgerScene } from './LedgerScene'
import { FieldScene } from './FieldScene'
import { AtlasScene } from './AtlasScene'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'

// JSX strips the newline between an expression and the text that follows it on
// the NEXT line, so `{PARTICIPANT_NAME}\n reads it` renders as "Dialecticreads
// it". Every assertion about this copy passed — length, presence, the testid —
// because none of them read the words. A screenshot did.

const ready = { status: 'ready' as const, objects: [], generatedAt: 'x', retry: () => {} }
const readyMarks = { status: 'ready' as const, marks: [], generatedAt: 'x', refresh: () => {} }
const readyAtlas = {
  status: 'ready' as const,
  projection: { generated_at: 'x', nodes: [], edges: [] },
  retry: () => {},
}

describe('scene copy reads as sentences', () => {
  it.each([
    ['Library', <LibraryScene state={ready} />],
    ['Ledger', <LedgerScene state={ready} />],
    ['Field', <FieldScene state={readyMarks} objects={ready} />],
    ['Atlas', <AtlasScene state={readyAtlas} onNavigate={vi.fn()} />],
  ])('%s never runs the participant name into the next word', (_name, element) => {
    render(element)
    const text = screen.getByTestId('scene-empty').textContent ?? ''
    // The name must always be followed by a space or ordinary punctuation —
    // never immediately by another letter.
    expect(text).not.toMatch(new RegExp(`${PARTICIPANT_NAME}[a-z]`))
  })
})

describe('Field empty state teaches (SceneEmpty four-question contract)', () => {
  it('answers what/what-lands/how/what-you-can-do, with no fake action button', () => {
    render(<FieldScene state={readyMarks} objects={ready} />)
    const empty = screen.getByTestId('scene-empty')
    const text = empty.textContent ?? ''
    expect(text).toMatch(/reasoning laid out/i)
    expect(text).toMatch(/positions/i)
    expect(text).toMatch(/provisional/i)
    expect(text).toMatch(/confirm/i)
    expect(text).toMatch(/contest/i)
    // The on-ramp is talking, not a button — no <button> lives inside the
    // empty state's own markup (SceneEmpty's `action` slot is unused here).
    expect(empty.querySelector('button')).toBeNull()
  })
})
