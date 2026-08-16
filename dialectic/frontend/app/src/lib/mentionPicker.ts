import { PARTICIPANT_NAME } from './productIdentity'

/**
 * The @-picker's pure core: given the composer's text and caret, decide
 * whether an @-token is being typed and which candidates match it.
 *
 * Kept out of the component so the interesting part — where a token starts,
 * what counts as still typing it, and what replacement text results — is
 * testable without a DOM, a render, or a keyboard.
 */

export interface MentionCandidate {
  /** What gets inserted after the @. */
  handle: string
  /** What the reader sees in the list. */
  label: string
  kind: 'human' | 'participant'
}

export interface MentionQuery {
  /** Index of the '@' in the source text. */
  start: number
  /** Index just past the partial handle (the caret). */
  end: number
  /** What has been typed after the @, possibly empty. */
  partial: string
}

/**
 * An @ only opens the picker at a word boundary, so an email address and a
 * handle already followed by punctuation do not.
 */
const TRIGGER_RE = /(?:^|[\s(])@([A-Za-z][\w-]*|)$/

export function mentionQueryAt(text: string, caret: number): MentionQuery | null {
  const before = text.slice(0, caret)
  const match = TRIGGER_RE.exec(before)
  if (!match) return null
  const partial = match[1]
  return { start: caret - partial.length - 1, end: caret, partial }
}

/**
 * Candidates for a partial, participant last.
 *
 * WHY the participant is last and not first: a human typing "@" in a room of
 * humans is usually reaching for a human. Dialectic answers when addressed
 * either way, and it is the one name in the room that never fails to notice.
 */
export function matchCandidates(
  partial: string,
  names: string[],
): MentionCandidate[] {
  const needle = partial.toLowerCase()
  const humans: MentionCandidate[] = names
    .map((name) => ({
      handle: name.trim().split(/\s+/)[0] ?? name,
      label: name,
      kind: 'human' as const,
    }))
    .filter((c) => c.handle.toLowerCase().startsWith(needle))

  const participant: MentionCandidate[] = PARTICIPANT_NAME.toLowerCase().startsWith(needle)
    ? [{ handle: PARTICIPANT_NAME, label: PARTICIPANT_NAME, kind: 'participant' }]
    : []

  return [...humans, ...participant]
}

/**
 * Apply a choice, returning the new text and where the caret belongs.
 *
 * The trailing space is deliberate: without it the very next character
 * re-opens the picker on a handle the user has already finished.
 */
export function applyMention(
  text: string,
  query: MentionQuery,
  candidate: MentionCandidate,
): { text: string; caret: number } {
  const inserted = `@${candidate.handle} `
  return {
    text: text.slice(0, query.start) + inserted + text.slice(query.end),
    caret: query.start + inserted.length,
  }
}
