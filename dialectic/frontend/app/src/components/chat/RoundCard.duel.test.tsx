import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RoundQuestion, RoundState } from '../../types'
import { RoundCard } from './RoundCard'
import { api } from '../../lib/api'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: {
      readRound: vi.fn(),
      recordForecast: vi.fn(),
      binRoundQuestion: vi.fn(),
      resolveRoundQuestion: vi.fn(),
    },
  }
})

afterEach(() => vi.clearAllMocks())

const ROOM = 'room-1'
const CARD = 'card-1'
const QID = 'q-1'
const DAN = 'dan-uuid'
const NAMES = { [DAN]: 'Dan' }

function question(over: Partial<RoundQuestion> = {}): RoundQuestion {
  return {
    commitment_id: QID,
    claim: 'Does the BOJ raise at or before the December meeting?',
    closes: '2099-12-19',
    status: 'active',
    resolution: null,
    my_forecast: null,
    my_peer_forecast: null,
    my_revisions: 0,
    house_committed: false,
    revealed: false,
    waiting_on_other: false,
    ...over,
  }
}

function state(q: RoundQuestion): RoundState {
  // `peers` is membership, not forecasts. It is what lets the card name Dan
  // in the second slider BEFORE he has answered — the only other place his
  // name appears is inside a forecast, which is sealed.
  return {
    message_id: CARD,
    questions: [q],
    peers: [{ user_id: DAN, display_name: 'Dan' }],
  }
}

function mount(q: RoundQuestion) {
  vi.mocked(api.readRound).mockResolvedValue(state(q))
  return render(<RoundCard roomId={ROOM} messageId={CARD} userNames={NAMES} />)
}

/**
 * The duel's three rules, asserted on the real component.
 *
 * These are deliberately RENDER tests rather than unit checks of a helper.
 * What can break here is the wiring — a number arriving in the response and
 * being drawn one state too early is invisible to any unit test, and on a
 * blind scoring surface it is the only defect that actually matters.
 */
describe('the seal', () => {
  it('draws no house number before both humans are in', async () => {
    // The fixture deliberately CARRIES a house forecast while `revealed` is
    // false — a shape the server must never send. Without it this test would
    // be vacuous: it would pass because there was nothing to render, not
    // because the card declined to render it. This is the second fence, and
    // a fence is only a fence if something is pushing on it.
    mount(question({
      my_forecast: 0.4,
      waiting_on_other: true,
      house_committed: true,
      house: { forecast: 0.72, revisions: 1, because: 'JGB 10y already near 2.95%.' },
    }))
    await screen.findByText(/sealed until they answer/)
    expect(screen.getByText(/the house is in too/)).toBeTruthy()
    // "is in" is allowed. A NUMBER is not.
    expect(document.body.textContent).not.toMatch(/72%/)
    expect(screen.queryByText(/JGB 10y/)).toBeNull()
  })

  it('draws the house beside them once revealed', async () => {
    mount(question({
      my_forecast: 0.4,
      revealed: true,
      others: [{ user_id: DAN, forecast: 0.75, revisions: 1 }],
      house: { forecast: 0.72, revisions: 1, because: 'JGB 10y already near 2.95%.' },
    }))
    await screen.findByText('72%')
    expect(screen.getByText(/JGB 10y already near 2\.95%/)).toBeTruthy()
  })
})

describe('the second slider', () => {
  it('is absent until asked for, and then sends the read', async () => {
    // The response replaces the card's state, so it must carry the forecast
    // back — otherwise the button reverts to "lock in" and the second half of
    // this test is asserting against a card that forgot the first half.
    vi.mocked(api.recordForecast).mockResolvedValue(
      state(question({ my_forecast: 0.4 })))
    mount(question({ my_forecast: 0.4 }))

    const open = await screen.findByText(/where will Dan land/)
    // Nothing is sent for an untouched control: an unopened slider is not a
    // guess of 50%.
    fireEvent.click(screen.getByText('revise'))
    await waitFor(() => expect(api.recordForecast).toHaveBeenCalled())
    expect(vi.mocked(api.recordForecast).mock.calls[0][4] ?? null).toBeNull()

    vi.mocked(api.recordForecast).mockClear()
    fireEvent.click(open)
    const slider = await screen.findByLabelText('Dan')
    fireEvent.change(slider, { target: { value: '0.3' } })
    fireEvent.click(screen.getByText('revise'))
    await waitFor(() => expect(api.recordForecast).toHaveBeenCalled())
    expect(vi.mocked(api.recordForecast).mock.calls[0][4]).toBe(0.3)
  })

  it('says which way you misread them', async () => {
    mount(question({
      my_forecast: 0.4,
      my_peer_forecast: 0.3,
      revealed: true,
      others: [{ user_id: DAN, forecast: 0.75, revisions: 1 }],
      peer_read_error: 0.45,
    }))
    await screen.findByText(/you read them low/)
    expect(screen.getByText('+45')).toBeTruthy()
  })
})

describe('the verdict', () => {
  it('offers no settle controls while the question is still open', async () => {
    mount(question({ closes: '2099-12-19', my_forecast: 0.4 }))
    await screen.findByText(/closes 2099-12-19/)
    expect(screen.queryByText('it happened')).toBeNull()
  })

  it('asks what happened once the close date has passed', async () => {
    vi.mocked(api.resolveRoundQuestion).mockResolvedValue(state(question()))
    mount(question({ closes: '2020-01-01', my_forecast: 0.4 }))
    fireEvent.click(await screen.findByText('it happened'))
    await waitFor(() => expect(api.resolveRoundQuestion)
      .toHaveBeenCalledWith(ROOM, QID, 'correct'))
  })

  it('reports coverage beside the Brier, never folded into it', async () => {
    mount(question({
      closes: '2020-01-01',
      status: 'resolved',
      resolution: 'incorrect',
      my_forecast: 0.1,
      revealed: true,
      others: [{ user_id: DAN, forecast: 0.75, revisions: 1 }],
      scores: [
        {
          user_id: DAN, actor: 'human', coverage: 0.3, log_score: -1.2,
          peer: -18.4, contested_days: 6, brier: 0.09,
          brier_final_answer: 0.09, lateness_gap: 0, days_scored: 6, bss: 0.64,
        },
      ],
    }))
    await screen.findByText(/in for 30%/)
    expect(screen.getByText('-18')).toBeTruthy()
    expect(screen.getByText(/clipped at 1%/)).toBeTruthy()
  })
})
