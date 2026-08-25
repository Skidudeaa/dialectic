import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HomeProposalItem } from '../../types'
import type { ProposalKind } from '../../types/workspace.ts'
import { ProposalInbox } from './ProposalInbox'
import { api } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: {
      getHomeProposals: vi.fn(),
    },
  }
})

afterEach(() => vi.clearAllMocks())

const item = (over: Partial<HomeProposalItem> = {}): HomeProposalItem => ({
  id: 'prop-1',
  proposal_kind: 'prediction_draft',
  source_message_id: 'msg-1',
  room_id: 'room-1',
  room_name: 'Iran/Hormuz Trading Room',
  branch_id: null,
  created_by: 'user-1',
  created_at: '2026-08-20T12:00:00Z',
  rationale: 'Oil breaks $95 by Friday on Hormuz closure risk.',
  payload: {},
  status: 'proposed',
  accepted_by: null,
  accepted_at: null,
  target_object: null,
  available_actions: ['accept', 'dismiss', 'inspect'],
  ...over,
})

function mount(proposals: HomeProposalItem[], onNavigate = vi.fn()) {
  vi.mocked(api.getHomeProposals).mockResolvedValue({ generated_at: '2026-08-24T12:00:00Z', proposals })
  render(<ProposalInbox onNavigate={onNavigate} />)
  return onNavigate
}

describe('ProposalInbox', () => {
  it('shows a checking note before the first response lands', async () => {
    mount([])
    expect(screen.getByText('Checking proposals…')).toBeInTheDocument()
    await screen.findByText(/Nothing pending/)
  })

  it('says so plainly when nothing is pending', async () => {
    mount([])
    expect(await screen.findByText('Nothing pending — no open proposals right now.')).toBeInTheDocument()
  })

  it('reads as unanswered, not as empty, when the door fails', async () => {
    vi.mocked(api.getHomeProposals).mockRejectedValue(new Error('boom'))
    render(<ProposalInbox onNavigate={vi.fn()} />)
    expect(await screen.findByText(/Proposals unavailable — boom/)).toBeInTheDocument()
    expect(screen.queryByText(/Nothing pending/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('lists a pending proposal with a human-readable kind, its room, status and rationale', async () => {
    mount([item()])
    await screen.findByRole('region', { name: 'Proposals' })
    expect(screen.getByText('Prediction')).toBeInTheDocument()
    expect(screen.getByText('Iran/Hormuz Trading Room')).toBeInTheDocument()
    expect(screen.getByText('Oil breaks $95 by Friday on Hormuz closure risk.')).toBeInTheDocument()
    expect(screen.getByText('proposed')).toBeInTheDocument()
  })

  it('keeps resolved proposals visible but out of the way, never gone', async () => {
    mount([
      item({ id: 'p-open', status: 'proposed', rationale: 'Still needs a call.' }),
      item({ id: 'p-done', status: 'accepted', rationale: 'Already decided.' }),
    ])
    await screen.findByRole('region', { name: 'Proposals' })

    const open = screen.getByText('Still needs a call.')
    const done = screen.getByText('Already decided.')
    // Never silently erased — it is still in the document...
    expect(done).toBeInTheDocument()
    // ...just demoted behind the fold, unlike the one still needing a human.
    expect(done.closest('details')).not.toBeNull()
    expect(open.closest('details')).toBeNull()
    expect(screen.getByText('Resolved')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('navigates to the exact room, branch and message a proposal names', async () => {
    const onNavigate = mount([
      item({ room_id: 'room-9', branch_id: 'branch-2', source_message_id: 'msg-42' }),
    ])
    await screen.findByRole('region', { name: 'Proposals' })
    fireEvent.click(screen.getByText('Oil breaks $95 by Friday on Hormuz closure risk.'))
    expect(onNavigate).toHaveBeenCalledWith({
      roomId: 'room-9',
      threadId: 'branch-2',
      messageId: 'msg-42',
    })
  })

  it('humanizes a proposal kind this build has never seen instead of breaking', async () => {
    mount([item({ proposal_kind: 'made_up_kind' as ProposalKind })])
    expect(await screen.findByText('Made Up Kind')).toBeInTheDocument()
  })

  it('retries a failed check without losing the retry affordance', async () => {
    vi.mocked(api.getHomeProposals).mockRejectedValueOnce(new Error('boom'))
    render(<ProposalInbox onNavigate={vi.fn()} />)
    await screen.findByText(/Proposals unavailable/)

    vi.mocked(api.getHomeProposals).mockResolvedValueOnce({ generated_at: '2026-08-24T12:00:00Z', proposals: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText(/Nothing pending/)).toBeInTheDocument()
  })
})
