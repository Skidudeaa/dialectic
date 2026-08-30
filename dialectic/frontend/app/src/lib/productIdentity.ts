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
): string {
  switch (speakerType) {
    case 'llm_primary':
      return PARTICIPANT_NAME
    case 'llm_provoker':
      return `${PARTICIPANT_NAME} · Provoker`
    case 'llm_annotator':
      return `${PARTICIPANT_NAME} · Note`
    case 'system':
      return 'System'
    default:
      return PARTICIPANT_NAME
  }
}

/**
 * The restrained signature that replaces the colored avatar circle
 * (design v2 §16.9 / §16.4):
 *
 *   AMO        A
 *   DAN        D
 *   DIALECTIC  )
 *
 * WHY a letter and not a color: §16.4 states plainly "color does not encode
 * participants" — the old avatar told you who was speaking by border hue
 * (teal for you, gold for the other human, amber for Dialectic's primary
 * voice, a dimmer gold for the provoker). That is exactly the encoding the
 * spec forbids. A human's mark is the first letter of their own name, so it
 * changes with who they actually are rather than which seat they sit in.
 * Every Dialectic mode — primary, provoker, annotator —
 * gets the same product glyph, because the voice is still Dialectic's; the
 * mode is already named in the byline text ("Dialectic · Provoker"), which
 * is where a mode distinction belongs, not in the mark.
 *
 * Lives beside `participantDisplayName` rather than in the component file:
 * `SignatureMark.tsx` exports only the component, so React Fast Refresh
 * (`react-refresh/only-export-components`) does not flag a mixed export.
 */
export function markGlyph(speakerType: Message['speaker_type'], authorName: string): string {
  if (speakerType === 'human') {
    return authorName.trim().charAt(0).toUpperCase() || '?'
  }
  if (speakerType === 'system') return '·'
  return PARTICIPANT_SIGNATURE
}
