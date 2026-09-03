import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { YourMove } from './YourMove'
import { api, type RoundMove } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return { ...actual, api: { ...actual.api, getRoundMoves: vi.fn() } }
})

afterEach(() => vi.clearAllMocks())

const move = (over: Partial<RoundMove>): RoundMove => ({
  commitment_id: 'c1', room_id: 'r1', room_name: 'Iran/Hormuz', thread_id: 't1', message_id: 'm1',
  claim: 'Brent settles above $100 on Sep 30', closes: '2026-09-30', mine: false, peers_moved: [], ...over,
})

describe('YourMove', () => {
  it('puts the question a peer answered and you have not on top, naming the peer and never a number', async () => {
    vi.mocked(api.getRoundMoves).mockResolvedValue({ your_move: 2, moves: [
      move({ commitment_id: 'done', mine: true, claim: 'Already forecast' }),
      move({ commitment_id: 'dan', peers_moved: ['Dan'] }),
    ] })
    render(<YourMove onNavigate={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/Your move · 1/)).toBeInTheDocument())
    const items = screen.getAllByRole('button')
    expect(items[0]).toHaveTextContent('Dan moved')
    expect(items[1]).toHaveTextContent('you forecast')
    expect(document.body.textContent).not.toMatch(/\d+%/)
  })

  it('navigates to the round card in its room', async () => {
    const onNavigate = vi.fn()
    vi.mocked(api.getRoundMoves).mockResolvedValue({ your_move: 1, moves: [move({ peers_moved: ['Dan'] })] })
    render(<YourMove onNavigate={onNavigate} />)
    fireEvent.click(await screen.findByRole('button'))
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'r1', threadId: 't1', messageId: 'm1' })
  })

  it('says when nothing waits, and hides the list', async () => {
    vi.mocked(api.getRoundMoves).mockResolvedValue({ your_move: 0, moves: [] })
    render(<YourMove onNavigate={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/No open question waits on you/)).toBeInTheDocument())
    expect(screen.queryByRole('button')).toBeNull()
  })
})
