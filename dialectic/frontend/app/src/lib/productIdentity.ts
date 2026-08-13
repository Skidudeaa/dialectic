import type { Message } from '../types'

// The product IS the participant. Provider and model identifiers remain in
// technical provenance (message metadata, decision logs) but never in a primary
// product label — the visible name is Dialectic in every participant mode.
export const PRODUCT_NAME = 'Dialectic'
export const PARTICIPANT_NAME = 'Dialectic'
export const PARTICIPANT_SIGNATURE = ')'
export const ORIGIN_IMPRINT = 'DwoodAmo'

export function participantDisplayName(
  speakerType: Message['speaker_type'],
  personaName?: string | null,
): string {
  switch (speakerType) {
    case 'llm_primary':
      return PARTICIPANT_NAME
    case 'llm_provoker':
      return `${PARTICIPANT_NAME} · Provoker`
    case 'llm_annotator':
      return `${PARTICIPANT_NAME} · Note`
    case 'llm_persona':
      return personaName?.trim() || PARTICIPANT_NAME
    case 'system':
      return 'System'
    default:
      return PARTICIPANT_NAME
  }
}
