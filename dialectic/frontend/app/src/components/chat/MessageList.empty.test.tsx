import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageList } from './MessageList'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'

// Twelve of twenty-three production rooms hold no message at all, so this is
// not an edge case — for most first visits the empty state IS the room. It
// said "Claude will join the conversation", which is both uninformative and
// stale: the participant was renamed to Dialectic in Task Group A5, and the
// shipped bundle still carries the old sentence.

describe('MessageList — the empty room', () => {
  it('names the participant from product identity, never a provider', () => {
    const { container } = render(
      <MessageList messages={[]} currentUserId="u1" emptyKind="dialogue" />,
    )
    expect(container.textContent).not.toMatch(/\bClaude\b/)
    expect(container.textContent).toContain(PARTICIPANT_NAME)
  })

  it('says what the room does, not just that it is empty', () => {
    render(<MessageList messages={[]} currentUserId="u1" emptyKind="dialogue" />)
    // The one thing a newcomer cannot guess and must know: the participant
    // joins on its own judgment rather than waiting to be addressed.
    expect(screen.getByTestId('empty-room-premise')).toBeInTheDocument()
  })

  it('tells them how to summon it explicitly', () => {
    render(<MessageList messages={[]} currentUserId="u1" emptyKind="dialogue" />)
    // @Dialectic is the primary summon (A5); the aliases stay compatible but
    // the door a new user is shown should be the primary one.
    expect(screen.getByTestId('empty-room-premise')).toHaveTextContent(
      `@${PARTICIPANT_NAME}`,
    )
  })

  it('leaves the Home hearth alone', () => {
    // Home's empty table is deliberately quiet — the house sits above it, and
    // turning it into an explainer would shout over the House.
    render(<MessageList messages={[]} currentUserId="u1" emptyKind="hearth" />)
    expect(screen.queryByTestId('empty-room-premise')).not.toBeInTheDocument()
    expect(screen.getByText(/The table/i)).toBeInTheDocument()
  })
})
