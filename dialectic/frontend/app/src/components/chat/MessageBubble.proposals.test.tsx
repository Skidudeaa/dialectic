import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Message, MessageMetadata } from '../../types'
import { MessageBubble } from './MessageBubble'

/**
 * D4 — migration safety, asserted on the real component.
 *
 * A message carrying today's RAW metadata — the exact shapes the relays and
 * hoists write right now — must still render every card after the envelope
 * took over deciding what is accepted. Nothing in the database is rewritten,
 * so old and new shapes coexist and this is the test that says so.
 *
 * WHY a render and not a unit check of the helper: the helper is tested
 * separately. What could still break is the wiring — a card reading the wrong
 * coordinate would render an Accept button on something already accepted, and
 * no unit test of either half would see it.
 */

const MID = '22222222-2222-4222-8222-222222222222'

function message(metadata: MessageMetadata): Message {
  return {
    id: MID,
    thread_id: 'thread-1',
    sequence: 1,
    created_at: '2026-08-12T12:00:00Z',
    speaker_type: 'llm_primary',
    message_type: 'text',
    content: 'The desk should take a view here.',
    metadata,
  } as unknown as Message
}

const RAW = {
  proposal: {
    statement: 'Brent over 90 by October', confidence: 0.6,
    deadline: '2026-10-01', accepted: false,
  },
  thesis_proposal: {
    title: 'Strait risk', claim: 'the strait shuts', monthly_budget: 5000,
  },
  reading_proposal: {
    url: 'https://example.test/a', title: 'The tanker rates move first',
    summary: 'what it argues', accepted: false,
  },
  resolution_proposal: {
    prediction_id: 'p1', statement: 'Brent over 90', verdict: 'correct',
    rationale: 'settled above 90 all week', accepted: false,
  },
  commitment_proposals: [
    { claim: 'I close before CPI', resolution_criteria: 'flat',
      category: 'commitment', accepted: false },
  ],
} as unknown as MessageMetadata

function renderBubble(metadata: MessageMetadata) {
  return render(
    <MessageBubble message={message(metadata)} isSelf={false} authorName="Dialectic" />,
  )
}

describe('a message carrying today raw proposal metadata', () => {
  it('still renders every card', () => {
    renderBubble(RAW)
    expect(screen.getByText('Drafted prediction')).toBeInTheDocument()
    expect(screen.getByText('Proposed thesis')).toBeInTheDocument()
    expect(screen.getByText('File in the library')).toBeInTheDocument()
    expect(screen.getByText('Prediction resolution')).toBeInTheDocument()
    expect(screen.getByText('Heard a commitment')).toBeInTheDocument()
  })

  it('offers the action on what is still open', () => {
    renderBubble(RAW)
    expect(screen.getAllByRole('button', { name: 'Accept' })).toHaveLength(2)
    expect(screen.getByRole('button', { name: /Put it on record/ }))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Draft the cascade/ }))
      .toBeInTheDocument()
  })

  it('disarms a card the server already stamped, and keeps it visible', () => {
    // §8.4: an accepted proposal remains inspectable. It does not disappear as
    // if no proposal had ever been made.
    renderBubble({
      ...RAW,
      proposal: { ...(RAW as never as Record<string, Record<string, unknown>>).proposal,
                  accepted: true },
    } as unknown as MessageMetadata)
    expect(screen.getByText('Drafted prediction')).toBeInTheDocument()
    expect(screen.getByText('Brent over 90 by October')).toBeInTheDocument()
    expect(screen.getByText('logged to tradingDesk')).toBeInTheDocument()
    expect(screen.queryAllByRole('button', { name: 'Accept' })).toHaveLength(1)
  })

  it('disarms the right entry of a list, by coordinate', () => {
    // The failure this catches: a card reading the wrong index would disarm a
    // commitment the human never accepted, and arm one they did.
    renderBubble({
      ...RAW,
      commitment_proposals: [
        { claim: 'I close before CPI', resolution_criteria: 'flat',
          category: 'commitment', accepted: true },
        { claim: 'I halve the position', resolution_criteria: 'size',
          category: 'commitment', accepted: false },
      ],
    } as unknown as MessageMetadata)
    expect(screen.getByText('on the record')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Put it on record/ }))
      .toHaveLength(1)
  })

  it('gives a claim check no action at all', () => {
    // A nudge, not a decision. It shares the metadata column with proposals
    // and must never pick up an Accept button from passing nearby.
    renderBubble({
      claim_check: {
        url: 'https://x.test', verdict: 'mixed',
        note: 'the article says less than the message',
      },
    } as unknown as MessageMetadata)
    expect(screen.getByText(/the article says less/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
  })
})
