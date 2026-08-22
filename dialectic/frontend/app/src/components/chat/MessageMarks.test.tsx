import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MessageMarks } from './MessageMarks'
import type { FieldMark } from '../../types/workspace.ts'
import { api } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return { ...actual, api: { ...actual.api, postFieldReview: vi.fn() } }
})

afterEach(() => vi.clearAllMocks())

const mark = (overrides: Partial<FieldMark> & { id: string }): FieldMark => ({
  room_id: 'r1', thread_id: null, relation: 'emerging_position', origin: 'inferred',
  review: 'provisional', deliberative_status: 'active', subjects: [], title: 'Rates fall',
  payload: {}, supersedes_id: null, caused_by_id: null, actor_user_id: null,
  provenance: 'field_inference', created_at: '2026-08-13T10:00:00Z', reviews: [],
  ...overrides,
})

/**
 * The marks row is where the Field is actually reachable from — and until
 * 2026-08-21 it was two buttons with no statement of what they meant. 85 marks
 * in production, zero human reviews, ever. The machinery was never broken.
 *
 * So what is under test here is the EXPLANATION as much as the actions: that a
 * reader who has never seen a mark before is told what one is and what their
 * tap does, at the point of the tap, and that the definition is a real control
 * rather than a hover-only `title` nobody on a phone can reach.
 */
describe('MessageMarks', () => {
  it('renders nothing at all when the message carries no marks', () => {
    const { container } = render(<MessageMarks roomId="r1" marks={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('says what a mark is and what a review does, beside the buttons that do it', () => {
    render(<MessageMarks roomId="r1" marks={[mark({ id: 'field_mark:1' })]} />)
    const lede = document.querySelector('.msg-marks-lede')
    expect(lede?.textContent).toMatch(/provisional, and not conclusions/i)
    expect(lede?.textContent).toMatch(/confirm makes one solid/i)
    expect(lede?.textContent).toMatch(/contest puts it on notice/i)
    // Nothing is overwritten anywhere in this product; the row has to say so,
    // because "contest" reads as destructive to someone meeting it cold.
    expect(lede?.textContent).toMatch(/Neither overwrites/i)
  })

  it('carries the definition as a button, never a hover-only tooltip', () => {
    render(<MessageMarks roomId="r1" marks={[mark({ id: 'field_mark:1' })]} />)
    const trigger = screen.getByRole('button', { name: 'Field marks' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(screen.getByRole('note').textContent).toMatch(/provisional note/i)
  })

  it('states it ONCE per message, not once per mark', () => {
    // A definition repeated three times under one message is noise, and noise
    // is what got the previous surface ignored.
    render(
      <MessageMarks
        roomId="r1"
        marks={[mark({ id: 'field_mark:1' }), mark({ id: 'field_mark:2', title: 'A tension' })]}
      />,
    )
    expect(document.querySelectorAll('.msg-marks-lede')).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Confirm' })).toHaveLength(2)
  })

  it('still sends the review, with the bare row id the route wants', async () => {
    vi.mocked(api.postFieldReview).mockResolvedValue(undefined as never)
    const onReviewed = vi.fn()
    render(
      <MessageMarks roomId="r1" marks={[mark({ id: 'field_mark:abc' })]} onReviewed={onReviewed} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Contest' }))
    // `field_mark:` is the workspace-object prefix; the review route wants the row.
    await waitFor(() =>
      expect(api.postFieldReview).toHaveBeenCalledWith('r1', 'abc', { action: 'contest' }))
    await waitFor(() => expect(onReviewed).toHaveBeenCalled())
  })

  it('says so when a review does not land', async () => {
    // Silently doing nothing reads as "my confirm was recorded", which is the
    // one thing it must never imply.
    vi.mocked(api.postFieldReview).mockRejectedValue(new Error('boom'))
    render(<MessageMarks roomId="r1" marks={[mark({ id: 'field_mark:1' })]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText(/not recorded/i)).toBeInTheDocument()
  })
})
