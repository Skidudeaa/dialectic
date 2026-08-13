import { describe, expect, it } from 'vitest'
import {
  ORIGIN_IMPRINT,
  PARTICIPANT_NAME,
  PARTICIPANT_SIGNATURE,
  PRODUCT_NAME,
  participantDisplayName,
} from './productIdentity'

describe('product identity', () => {
  it('keeps Dialectic as product and participant', () => {
    expect(PRODUCT_NAME).toBe('Dialectic')
    expect(PARTICIPANT_NAME).toBe('Dialectic')
    expect(PARTICIPANT_SIGNATURE).toBe(')')
    expect(ORIGIN_IMPRINT).toBe('DwoodAmo')
  })

  it('names participant modes without exposing a provider', () => {
    expect(participantDisplayName('llm_primary')).toBe('Dialectic')
    expect(participantDisplayName('llm_provoker')).toBe('Dialectic · Provoker')
    expect(participantDisplayName('llm_annotator')).toBe('Dialectic · Note')
    expect(participantDisplayName('system')).toBe('System')
  })
})
