import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposeMenu } from './ProposeMenu'
import { api, ApiError } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'

// "Make a move" (§1.11, §5.3): a human composes one of the four proposal
// kinds and it lands as an ordinary message with a validated metadata
// block. These tests cover the surface's own contract — no hover
// dependency (§17.4), the kind picker, per-kind field shape, and that the
// submission it builds carries the exact slot names proposal_intake.py
// (and proposal_envelope.PROPOSAL_SLOTS) expect. Server-side validation
// itself is covered by tests/test_propose_surface_pg.py — this file only
// proves the client builds the right document and reacts to the server's
// answer.

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ApiError: actual.ApiError,
    api: { proposeMove: vi.fn() },
  }
})

const THREAD_ID = 'thread-propose-1'

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({
    currentThread: { id: THREAD_ID, room_id: 'room-1', title: 'Main' } as never,
  })
})

describe('ProposeMenu — the trigger', () => {
  it('is a visible, always-present button — not a hover reveal', () => {
    render(<ProposeMenu />)
    const trigger = screen.getByRole('button', { name: /make a move/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger).toBeVisible()
    // No panel until an actual click — nothing here is wired to
    // pointerenter/mouseover.
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('disables with the composer (no socket / no open thread)', () => {
    render(<ProposeMenu disabled />)
    expect(screen.getByRole('button', { name: /make a move/i })).toBeDisabled()
  })

  it('opens the kind picker on click and closes on Escape — never on mouseleave', () => {
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    expect(screen.getByRole('dialog', { name: 'Make a move' })).toBeInTheDocument()

    // Moving the pointer away must not close it.
    fireEvent.mouseLeave(screen.getByRole('dialog'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('closes on a click outside the panel', () => {
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('offers all four PROPOSAL_SLOTS kinds — resolution excluded', () => {
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    expect(screen.getByRole('button', { name: 'Prediction' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thesis' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reading' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Commitment' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resolution/i })).toBeNull()
  })
})

describe('ProposeMenu — prediction draft', () => {
  function openPredictionForm() {
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Prediction' }))
  }

  it('keeps Send disabled until statement, confidence and deadline are all present', () => {
    openPredictionForm()
    const send = screen.getByRole('button', { name: /send to the room/i })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Statement'), { target: { value: 'Brent over 90' } })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Confidence (%)'), { target: { value: '70' } })
    expect(send).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Deadline'), { target: { value: '2026-10-01' } })
    expect(send).toBeEnabled()
  })

  it('posts the proposal slot proposal_envelope.PROPOSAL_SLOTS expects', async () => {
    vi.mocked(api.proposeMove).mockResolvedValue({ id: 'm1' })
    openPredictionForm()
    fireEvent.change(screen.getByLabelText('Statement'), { target: { value: 'Brent over 90' } })
    fireEvent.change(screen.getByLabelText('Confidence (%)'), { target: { value: '70' } })
    fireEvent.change(screen.getByLabelText('Deadline'), { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    await waitFor(() => expect(api.proposeMove).toHaveBeenCalledTimes(1))
    const [threadId, content, metadata] = vi.mocked(api.proposeMove).mock.calls[0]
    expect(threadId).toBe(THREAD_ID)
    expect(content).toBe('Brent over 90')
    expect(metadata).toEqual({
      proposal: { statement: 'Brent over 90', confidence: 0.7, deadline: '2026-10-01' },
    })
    expect(await screen.findByText(/sent/i)).toBeInTheDocument()
  })

  it('lets a note override the default message body', async () => {
    vi.mocked(api.proposeMove).mockResolvedValue({ id: 'm1' })
    openPredictionForm()
    fireEvent.change(screen.getByLabelText('Statement'), { target: { value: 'Brent over 90' } })
    fireEvent.change(screen.getByLabelText('Confidence (%)'), { target: { value: '70' } })
    fireEvent.change(screen.getByLabelText('Deadline'), { target: { value: '2026-10-01' } })
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: 'Worth logging now.' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    await waitFor(() => expect(api.proposeMove).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.proposeMove).mock.calls[0][1]).toBe('Worth logging now.')
  })

  it('surfaces a server rejection instead of silently succeeding', async () => {
    vi.mocked(api.proposeMove).mockRejectedValue(new ApiError('deadline must be an ISO date', 422))
    openPredictionForm()
    fireEvent.change(screen.getByLabelText('Statement'), { target: { value: 'Brent over 90' } })
    fireEvent.change(screen.getByLabelText('Confidence (%)'), { target: { value: '70' } })
    fireEvent.change(screen.getByLabelText('Deadline'), { target: { value: '2026-10-01' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('deadline must be an ISO date')
    expect(screen.queryByText(/^sent/i)).toBeNull()
  })
})

describe('ProposeMenu — thesis proposal', () => {
  it('posts under the thesis_proposal slot with the default budget', async () => {
    vi.mocked(api.proposeMove).mockResolvedValue({ id: 'm1' })
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Thesis' }))
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Strait risk' } })
    fireEvent.change(screen.getByLabelText('Claim'), { target: { value: 'the strait shuts' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    await waitFor(() => expect(api.proposeMove).toHaveBeenCalledTimes(1))
    const [, content, metadata] = vi.mocked(api.proposeMove).mock.calls[0]
    expect(content).toBe('the strait shuts')
    expect(metadata).toEqual({
      thesis_proposal: { title: 'Strait risk', claim: 'the strait shuts', monthly_budget: 5000 },
    })
  })
})

describe('ProposeMenu — reading draft', () => {
  it('requires an http(s) url and posts key_claims as a list', async () => {
    vi.mocked(api.proposeMove).mockResolvedValue({ id: 'm1' })
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Reading' }))
    const send = screen.getByRole('button', { name: /send to the room/i })

    fireEvent.change(screen.getByLabelText('URL'), { target: { value: 'not-a-url' } })
    fireEvent.change(screen.getByLabelText('Summary'), { target: { value: 'what it argues' } })
    expect(send).toBeDisabled()

    fireEvent.change(screen.getByLabelText('URL'), { target: { value: 'https://example.test/a' } })
    fireEvent.change(screen.getByLabelText('Key claims (one per line, optional)'), {
      target: { value: 'first claim\nsecond claim' },
    })
    expect(send).toBeEnabled()
    fireEvent.click(send)

    await waitFor(() => expect(api.proposeMove).toHaveBeenCalledTimes(1))
    const [, , metadata] = vi.mocked(api.proposeMove).mock.calls[0]
    expect(metadata).toEqual({
      reading_proposal: {
        url: 'https://example.test/a',
        summary: 'what it argues',
        key_claims: ['first claim', 'second claim'],
      },
    })
  })
})

describe('ProposeMenu — commitment proposal', () => {
  it('posts a one-item commitment_proposals list, category defaulted', async () => {
    vi.mocked(api.proposeMove).mockResolvedValue({ id: 'm1' })
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Commitment' }))
    fireEvent.change(screen.getByLabelText('Claim'), { target: { value: 'I close before CPI' } })
    fireEvent.change(screen.getByLabelText('Resolution criteria'), { target: { value: 'flat by then' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    await waitFor(() => expect(api.proposeMove).toHaveBeenCalledTimes(1))
    const [, , metadata] = vi.mocked(api.proposeMove).mock.calls[0]
    expect(metadata).toEqual({
      commitment_proposals: [
        { claim: 'I close before CPI', resolution_criteria: 'flat by then', category: 'prediction' },
      ],
    })
  })
})

describe('ProposeMenu — no open thread', () => {
  it('refuses to submit rather than posting without a destination', async () => {
    useAppStore.setState({ currentThread: null })
    render(<ProposeMenu />)
    fireEvent.click(screen.getByRole('button', { name: /make a move/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Commitment' }))
    fireEvent.change(screen.getByLabelText('Claim'), { target: { value: 'I close before CPI' } })
    fireEvent.change(screen.getByLabelText('Resolution criteria'), { target: { value: 'flat by then' } })
    fireEvent.click(screen.getByRole('button', { name: /send to the room/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/no open branch/i)
    expect(api.proposeMove).not.toHaveBeenCalled()
  })
})
