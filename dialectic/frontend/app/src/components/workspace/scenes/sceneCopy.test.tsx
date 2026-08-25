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
  projection: { generated_at: 'x', nodes: [], edges: [], scopes: [] },
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

/**
 * The same trap, on the surfaces that are NOT empty.
 *
 * The 2026-08-21 orientation lines interpolate a `<Explain>` element into
 * running prose, which is precisely the shape that loses its spaces: JSX drops
 * the newline between an expression and the text on the next line, so
 * `</Explain>\n— provisional` renders as "Field marks— provisional". Every
 * structural assertion still passes. Only reading the words catches it, and the
 * explicit `{' '}` joins are what these pin.
 *
 * SCENE_PRIMER needs no entry here — it is plain strings with no interpolation,
 * and its totality and no-state-in-prose contracts live in SceneMasthead.test.tsx,
 * beside the component that renders it.
 */
describe('orientation lines read as sentences', () => {
  const populated = {
    status: 'ready' as const,
    generatedAt: 'x',
    refresh: () => {},
    marks: [{
      id: 'field_mark:1', room_id: 'r1', thread_id: null,
      relation: 'emerging_position' as const, origin: 'inferred' as const,
      review: 'provisional' as const, deliberative_status: 'active' as const,
      subjects: [], title: 'Rates fall', payload: {}, supersedes_id: null,
      caused_by_id: null, actor_user_id: null, provenance: 'field_inference',
      created_at: '2026-08-13T10:00:00Z', reviews: [],
    }],
  }

  it('keeps the space on both sides of the Field lede’s glossary term', () => {
    render(<FieldScene state={populated} objects={ready} onOpen={vi.fn()} />)
    const lede = document.querySelector('.field-lede')?.textContent ?? ''
    expect(lede).toMatch(/Field marks — provisional, and not conclusions\. Tap a row/)
    expect(lede).toMatch(/earned the mark\. Nothing marked here outranks/)
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
