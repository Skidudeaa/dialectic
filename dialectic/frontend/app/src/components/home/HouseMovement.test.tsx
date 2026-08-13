import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { HomeActivityMovement } from '../../types'
import { HouseMovement } from './HouseMovement'

const item = (over: Partial<HomeActivityMovement> = {}): HomeActivityMovement => ({
  kind: 'reading_filed',
  room_id: 'room-1',
  thread_id: null,
  object_id: 'obj-1',
  title: 'The yen sinks back toward 160',
  state: 'proposal',
  requires_judgment: false,
  occurred_at: '2026-08-12T12:00:00Z',
  destination: '/?room=room-1',
  ...over,
})

describe('HouseMovement', () => {
  it('renders nothing when the house has not moved', () => {
    const { container } = render(<HouseMovement movement={[]} onNavigate={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('names what moved and where it came from', () => {
    render(<HouseMovement movement={[item()]} onNavigate={vi.fn()} />)
    expect(screen.getByText('The yen sinks back toward 160')).toBeInTheDocument()
    expect(screen.getByText(/reading filed/i)).toBeInTheDocument()
  })

  it('navigates to the item exact destination, branch included', () => {
    const onNavigate = vi.fn()
    render(
      <HouseMovement
        movement={[item({ thread_id: 'branch-9', destination: '/?room=room-1&thread=branch-9' })]}
        onNavigate={onNavigate}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /yen sinks/i }))
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'room-1', threadId: 'branch-9' })
  })

  it('marks only items a human must answer', () => {
    render(
      <HouseMovement
        movement={[
          item({ kind: 'prediction_review', title: 'Verdict needed', requires_judgment: true, object_id: 'o2' }),
          item({ kind: 'echo_created', title: 'Cited elsewhere', requires_judgment: false, object_id: 'o3' }),
        ]}
        onNavigate={vi.fn()}
      />,
    )
    const needsYou = screen.getByRole('button', { name: /Verdict needed/ })
    const arrival = screen.getByRole('button', { name: /Cited elsewhere/ })
    expect(needsYou.className).toMatch(/needs-judgment/)
    expect(arrival.className).not.toMatch(/needs-judgment/)
  })
})
