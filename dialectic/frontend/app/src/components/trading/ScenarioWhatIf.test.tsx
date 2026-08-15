import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ScenarioWhatIf } from './ScenarioWhatIf'
import { api, ApiError } from '../../lib/api'
import type { ScenarioEvaluation, ThesisScenario } from '../../types/trading'

// The what-if row is the only cockpit module that fetches directly
// (api.evaluateScenario). These tests cover: rendering authored
// probabilities, the evaluate → result round trip, the failure → Retry
// round trip, and the disabled-while-pending state. Everything else about
// the module (chips, tables, notes) is exercised implicitly by these
// scenarios; the contract this file owns is the api interaction.

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ApiError: actual.ApiError,
    api: { evaluateScenario: vi.fn() },
  }
})

const ROOM_ID = 'room-scn-1'

const SCENARIOS: ThesisScenario[] = [
  { id: 'scn-a', name: 'Oil Shock Deepens', probability: 0.35, notes: 'Brent breaks 100 and stays there.' },
  { id: 'scn-b', name: 'De-escalation', probability: 0.2 },
]

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ScenarioWhatIf — rows', () => {
  it('renders scenario rows with names and authored probabilities', () => {
    render(<ScenarioWhatIf roomId={ROOM_ID} scenarios={SCENARIOS} />)
    expect(screen.getByText('Oil Shock Deepens')).toBeInTheDocument()
    expect(screen.getByText('35.0%')).toBeInTheDocument()
    expect(screen.getByText('De-escalation')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()
  })
})

describe('ScenarioWhatIf — evaluate', () => {
  it('calls the api with (roomId, scenarioId) and renders the result', async () => {
    vi.mocked(api.evaluateScenario).mockResolvedValue({
      scenarioId: 'scn-a',
      probability: 0.42,
      changedNodes: { 'brent-95': { old: 'monitoring', new: 'fired' } },
      portfolioImpact: {
        USO: { pctImpact: -3.2, dollarImpact: -1200, from: 'long', to: 'flat' },
      },
    })

    render(<ScenarioWhatIf roomId={ROOM_ID} scenarios={SCENARIOS} />)
    const buttons = screen.getAllByRole('button', { name: /^evaluate$/i })
    fireEvent.click(buttons[0])

    expect(api.evaluateScenario).toHaveBeenCalledWith(ROOM_ID, 'scn-a')

    await waitFor(() => expect(screen.getByText(/hypothetical/i)).toBeInTheDocument())
    expect(screen.getByText(/brent-95/)).toBeInTheDocument()
    expect(screen.getByText(/monitoring/)).toBeInTheDocument()
    expect(screen.getByText(/fired/)).toBeInTheDocument()
    expect(screen.getByText('USO')).toBeInTheDocument()
  })

  it('shows an error line and Retry on failure, and Retry re-calls the api', async () => {
    vi.mocked(api.evaluateScenario)
      .mockRejectedValueOnce(new ApiError('desk unreachable', 503))
      .mockResolvedValueOnce({ scenarioId: 'scn-b', probability: 0.2 })

    render(<ScenarioWhatIf roomId={ROOM_ID} scenarios={SCENARIOS} />)
    const buttons = screen.getAllByRole('button', { name: /^evaluate$/i })
    fireEvent.click(buttons[1])

    const retry = await screen.findByRole('button', { name: /retry/i })
    expect(screen.getByText(/desk unreachable/i)).toBeInTheDocument()

    fireEvent.click(retry)
    expect(api.evaluateScenario).toHaveBeenCalledTimes(2)
    expect(api.evaluateScenario).toHaveBeenLastCalledWith(ROOM_ID, 'scn-b')

    await waitFor(() => expect(screen.queryByText(/desk unreachable/i)).toBeNull())
    await waitFor(() => expect(screen.getByText(/hypothetical/i)).toBeInTheDocument())
  })

  it('disables the button while evaluation is pending', async () => {
    let resolvePromise: (value: ScenarioEvaluation) => void = () => {}
    vi.mocked(api.evaluateScenario).mockReturnValue(
      new Promise<ScenarioEvaluation>((resolve) => { resolvePromise = resolve }),
    )

    render(<ScenarioWhatIf roomId={ROOM_ID} scenarios={SCENARIOS} />)
    const buttons = screen.getAllByRole('button', { name: /^evaluate$/i })
    fireEvent.click(buttons[0])

    await waitFor(() => expect(buttons[0]).toBeDisabled())
    expect(buttons[0]).toHaveTextContent(/evaluating/i)

    resolvePromise({ scenarioId: 'scn-a', probability: 0.4 })
    await waitFor(() => expect(buttons[0]).not.toBeDisabled())
  })
})
