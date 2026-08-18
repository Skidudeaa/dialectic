import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Message, MessageMetadata } from '../../types'
import { MessageBubble } from './MessageBubble'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'

// The accept-wiring test needs the api mocked (the tap must POST to the
// trade relay, not the network); everything else in this file renders only.
vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: { acceptTrade: vi.fn() },
  }
})

afterEach(() => {
  useAppStore.setState({ currentRoom: null } as never)
  vi.clearAllMocks()
})

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
  trade_proposal: {
    symbol: 'XOP', side: 'buy', dollars: 2000,
    rationale: 'brent node fired, refiners lag',
    prediction: { statement: 'XOP above 150', confidence: 0.65,
                  deadline: '2026-09-30' },
    accepted: false,
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
    expect(screen.getByText('Proposed paper trade')).toBeInTheDocument()
    expect(screen.getByText('Heard a commitment')).toBeInTheDocument()
  })

  it('offers the action on what is still open', () => {
    renderBubble(RAW)
    expect(screen.getAllByRole('button', { name: 'Accept' })).toHaveLength(3)
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
    expect(screen.queryAllByRole('button', { name: 'Accept' })).toHaveLength(2)
  })

  it('renders the trade card with its paired forecast, armed', () => {
    renderBubble(RAW)
    expect(screen.getByText(/Buy \$2,000 XOP/)).toBeInTheDocument()
    expect(screen.getByText('brent node fired, refiners lag')).toBeInTheDocument()
    expect(screen.getByText(/stakes: XOP above 150 — 65% by 2026-09-30/))
      .toBeInTheDocument()
    expect(screen.queryByText(/DISCRETIONARY/)).toBeNull()
  })

  it('labels a discretionary trade unscored instead of inventing a forecast', () => {
    renderBubble({
      trade_proposal: {
        symbol: 'CF', side: 'sell', dollars: 500,
        rationale: 'trim into strength', discretionary: true, accepted: false,
      },
    } as unknown as MessageMetadata)
    expect(screen.getByText(/Sell \$500 CF/)).toBeInTheDocument()
    expect(screen.getByText(/DISCRETIONARY — unscored/)).toBeInTheDocument()
    expect(screen.queryByText(/stakes:/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
  })

  it('disarms a filled trade and keeps it visible', () => {
    renderBubble({
      trade_proposal: {
        ...(RAW as never as Record<string, Record<string, unknown>>).trade_proposal,
        accepted: true,
      },
    } as unknown as MessageMetadata)
    expect(screen.getByText('Proposed paper trade')).toBeInTheDocument()
    expect(screen.getByText('filled on the paper book')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
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

  it('Accept on a trade posts to the relay and disarms optimistically', async () => {
    // The tap is the ONLY write; the card must address the accept by the
    // room in the store and THIS message's id.
    useAppStore.setState({
      currentRoom: { id: 'room-1', name: 'Scheme', token: 't', is_home: false },
    } as never)
    vi.mocked(api.acceptTrade).mockResolvedValue({ fill: { id: 7 }, prediction: null })
    renderBubble({
      trade_proposal: {
        symbol: 'XOP', side: 'buy', dollars: 2000, rationale: 'r',
        discretionary: true, accepted: false,
      },
    } as unknown as MessageMetadata)

    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))

    await waitFor(() => expect(api.acceptTrade).toHaveBeenCalledWith('room-1', MID))
    expect(await screen.findByText('filled on the paper book')).toBeInTheDocument()
  })

  it('a failed trade accept keeps the button armed for a fresh retry', async () => {
    // The server deliberately leaves `accepted` false on a relay failure —
    // the card must offer retry, not strand the human.
    useAppStore.setState({
      currentRoom: { id: 'room-1', name: 'Scheme', token: 't', is_home: false },
    } as never)
    vi.mocked(api.acceptTrade).mockRejectedValue(new Error('502'))
    renderBubble({
      trade_proposal: {
        symbol: 'XOP', side: 'buy', dollars: 2000, rationale: 'r',
        discretionary: true, accepted: false,
      },
    } as unknown as MessageMetadata)

    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))

    expect(await screen.findByText(/could not fill/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
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
