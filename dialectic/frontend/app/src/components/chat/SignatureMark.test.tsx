import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { markGlyph } from '../../lib/productIdentity'
import { SignatureMark } from './SignatureMark'

describe('SignatureMark — restrained signatures, not colored avatars', () => {
  it('marks a human by the first letter of their own name', () => {
    expect(markGlyph('human', 'Amo')).toBe('A')
    expect(markGlyph('human', 'Dan')).toBe('D')
  })

  it('marks every Dialectic mode with the product glyph, not a mode-specific one', () => {
    expect(markGlyph('llm_primary', 'Dialectic')).toBe(')')
    expect(markGlyph('llm_provoker', 'Dialectic')).toBe(')')
    expect(markGlyph('llm_annotator', 'Dialectic')).toBe(')')
    expect(markGlyph('llm_persona', 'Some Persona')).toBe(')')
  })

  it('never renders an inline style or class carrying a per-speaker color', () => {
    // The regression this guards: the old avatar told you who was speaking by
    // border hue. A signature mark that varies its own className or style by
    // speaker type would silently reintroduce that encoding.
    const { container: human } = render(
      <SignatureMark speakerType="human" authorName="Amo" />,
    )
    const { container: primary } = render(
      <SignatureMark speakerType="llm_primary" authorName="Dialectic" />,
    )
    const humanMark = human.querySelector('.signature-mark')!
    const primaryMark = primary.querySelector('.signature-mark')!
    expect(humanMark.className).toBe(primaryMark.className)
    expect(humanMark.getAttribute('style')).toBe(primaryMark.getAttribute('style'))
  })

  it('is decorative — the accessible name lives in the byline text beside it', () => {
    const { container } = render(<SignatureMark speakerType="human" authorName="Amo" />)
    expect(container.querySelector('.signature-mark')?.getAttribute('aria-hidden')).toBe('true')
  })
})
