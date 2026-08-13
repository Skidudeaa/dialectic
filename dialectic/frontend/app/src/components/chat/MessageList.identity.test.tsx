import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageList } from './MessageList'
import type { Message } from '../../types'
import { participantDisplayName } from '../../lib/productIdentity.ts'

// A5 established ONE definition of the participant's visible name in
// productIdentity.participantDisplayName. MessageList and SearchOverlay each
// kept a private copy of that mapping beside it, and both copies updated only
// the llm_primary arm — so a provoker or annotator turn still rendered a
// provider name in the byline, in the transcript and in every search result.
//
// The fix is not to correct the copies. It is to delete them, because a second
// definition is what let them drift in the first place.

const message = (speaker_type: Message['speaker_type'], id: string): Message => ({
  id,
  thread_id: 't1',
  sequence: 1,
  created_at: new Date('2026-08-13T10:00:00Z').toISOString(),
  speaker_type,
  user_id: null,
  message_type: 'text',
  content: `a ${speaker_type} turn`,
} as Message)

describe('MessageList — who is speaking', () => {
  it('labels every participant mode from the one shared definition', () => {
    render(
      <MessageList
        messages={[
          message('llm_primary', 'm1'),
          message('llm_provoker', 'm2'),
          message('llm_annotator', 'm3'),
        ]}
        currentUserId="u1"
      />,
    )

    for (const mode of ['llm_primary', 'llm_provoker', 'llm_annotator'] as const) {
      const expected = participantDisplayName(mode)
      expect(screen.getAllByText(expected).length).toBeGreaterThan(0)
    }
  })

  it('puts no provider name in any byline', () => {
    const { container } = render(
      <MessageList
        messages={[message('llm_provoker', 'm2'), message('llm_annotator', 'm3')]}
        currentUserId="u1"
      />,
    )
    expect(container.textContent).not.toMatch(/\bClaude\b/)
  })
})
