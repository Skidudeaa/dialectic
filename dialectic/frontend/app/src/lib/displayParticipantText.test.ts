import { describe, expect, it } from 'vitest'
import { displayParticipantText } from './productIdentity'

describe('participant identifiers in displayed prose', () => {
  it('preserves surrounding text and inline code while naming every persona', () => {
    const raw = 'Ask llm_primary; `llm_provoker` challenged llm_annotator.'
    expect(displayParticipantText(raw)).toBe('Ask Dialectic; `Dialectic · Provoker` challenged Dialectic · Note.')
    expect(raw).toContain('llm_primary')
  })

  it('leaves ordinary text and identifiers containing a longer name intact', () => {
    expect(displayParticipantText('Amo system my_llm_primary llm_primary_extra')).toBe(
      'Amo system my_llm_primary llm_primary_extra',
    )
  })
})
