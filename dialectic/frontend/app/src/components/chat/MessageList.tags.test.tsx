import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Message } from '../../types'
import { MessageList } from './MessageList'

const USER_ID = '11111111-1111-4111-8111-111111111111'

function message(
  id: string,
  sequence: number,
  createdAt: string,
  metadata: Message['metadata'] = null,
): Message {
  return {
    id,
    thread_id: 'thread-1',
    sequence,
    created_at: createdAt,
    speaker_type: 'human',
    user_id: USER_ID,
    user_name: 'Amo',
    message_type: 'text',
    content: `message ${sequence}`,
    metadata,
  }
}

describe('tagged continuation messages', () => {
  it('renders the filing tag even when the same person just spoke', () => {
    render(
      <MessageList
        messages={[
          message('message-1', 1, '2026-08-16T12:00:00Z'),
          message('message-2', 2, '2026-08-16T12:01:00Z', { tags: ['bug'] }),
        ]}
        currentUserId="another-user"
      />,
    )

    expect(screen.getByText('#bug')).toBeVisible()
  })
})
