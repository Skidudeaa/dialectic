import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LibraryScene } from './LibraryScene'
import { LedgerScene } from './LedgerScene'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'

// JSX strips the newline between an expression and the text that follows it on
// the NEXT line, so `{PARTICIPANT_NAME}\n reads it` renders as "Dialecticreads
// it". Every assertion about this copy passed — length, presence, the testid —
// because none of them read the words. A screenshot did.

const ready = { status: 'ready' as const, objects: [], generatedAt: 'x', retry: () => {} }

describe('scene copy reads as sentences', () => {
  it.each([
    ['Library', <LibraryScene state={ready} />],
    ['Ledger', <LedgerScene state={ready} />],
  ])('%s never runs the participant name into the next word', (_name, element) => {
    render(element)
    const text = screen.getByTestId('scene-empty').textContent ?? ''
    // The name must always be followed by a space or ordinary punctuation —
    // never immediately by another letter.
    expect(text).not.toMatch(new RegExp(`${PARTICIPANT_NAME}[a-z]`))
  })
})
