import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TrackRecordPanel } from './TrackRecordPanel'
import { LedgerScene } from './scenes/LedgerScene'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import type { Room } from '../../types'
import type { WorkspaceObjectsState } from '../../hooks/useWorkspaceObjects.ts'

// The Track Record panel is the Ledger's window onto the desk's claims
// ledger (One App: no duplicated td analytics surface). The contracts this
// file owns: the three visible states (loading / empty / populated), the
// silent states (no room, unbound room → nothing, never an error banner),
// and the LedgerScene mount.

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ApiError: actual.ApiError,
    api: {
      getTradingCalibration: vi.fn(),
      getTradingLeaderboard: vi.fn(),
      getTradingPortfolio: vi.fn(),
    },
  }
})

const ROOM = { id: 'room-1', name: 'Iran/Hormuz' } as unknown as Room

const CALIBRATION = {
  calibration: [
    { bucket: '0.6-0.7', midpoint: 0.65, total: 4, correct: 3, accuracy: 0.75 },
  ],
  total_predictions: 12,
  brier_score: 0.18,
  brier_skill_score: 0.28,
  bss_vs: 'market',
}

const LEADERBOARD = {
  rows: [
    {
      group: 'Claude', n: 12, brier: 0.18, bss: 0.28, bss_vs: 'market',
      accuracy: 0.67, bias: 0.04, provenance: 'EMPIRICAL',
    },
    {
      group: 'Amo', n: 3, brier: 0.31, bss: -0.24, bss_vs: 'ignorance',
      accuracy: 0.33, bias: 0.21, provenance: 'UNVERIFIED_INSUFFICIENT_SAMPLES',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  useAppStore.setState({ currentRoom: ROOM })
  // The equity curve is garnish: most tests run without a portfolio, and
  // the panel must render identically to before the feed existed.
  vi.mocked(api.getTradingPortfolio).mockRejectedValue(new Error('409'))
})

afterEach(() => {
  useAppStore.setState({ currentRoom: null })
})

describe('TrackRecordPanel — states', () => {
  it('renders nothing without a room', () => {
    useAppStore.setState({ currentRoom: null })
    const { container } = render(<TrackRecordPanel />)
    expect(container).toBeEmptyDOMElement()
    expect(api.getTradingCalibration).not.toHaveBeenCalled()
  })

  it('shows loading while the ledger reads are in flight', () => {
    vi.mocked(api.getTradingCalibration).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.getTradingLeaderboard).mockReturnValue(new Promise(() => {}))
    render(<TrackRecordPanel />)
    expect(screen.getByTestId('track-record-loading')).toBeInTheDocument()
  })

  it('shows the empty state when nothing has been scored', async () => {
    vi.mocked(api.getTradingCalibration).mockResolvedValue({
      calibration: [], total_predictions: 0, brier_score: null,
    })
    vi.mocked(api.getTradingLeaderboard).mockResolvedValue({ rows: [] })
    render(<TrackRecordPanel />)
    await waitFor(() =>
      expect(screen.getByTestId('track-record-empty')).toBeInTheDocument(),
    )
  })

  it('renders headline, leaderboard and calibration bars when populated', async () => {
    vi.mocked(api.getTradingCalibration).mockResolvedValue(CALIBRATION)
    vi.mocked(api.getTradingLeaderboard).mockResolvedValue(LEADERBOARD)
    render(<TrackRecordPanel />)

    await waitFor(() =>
      expect(screen.getByTestId('track-record-panel')).toBeInTheDocument(),
    )
    expect(screen.getByText('12 resolved')).toBeInTheDocument()
    expect(screen.getByText('Brier 0.18')).toBeInTheDocument()
    expect(screen.getByText('Claude')).toBeInTheDocument()
    expect(screen.getByText('Amo')).toBeInTheDocument()
    // The leaderboard split rides source_label by default.
    expect(api.getTradingLeaderboard).toHaveBeenCalledWith('room-1', 'source_label')
    // 10-bucket bars: one populated bucket in the fixture.
    expect(screen.getByText('Calibration')).toBeInTheDocument()
  })

  it('stays silent (renders nothing) when the room is unbound or the desk is down', async () => {
    vi.mocked(api.getTradingCalibration).mockRejectedValue(new Error('409'))
    vi.mocked(api.getTradingLeaderboard).mockRejectedValue(new Error('409'))
    const { container } = render(<TrackRecordPanel />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it('draws the equity-vs-SPY sparkline from marks joined to the unitized baseline', async () => {
    vi.mocked(api.getTradingCalibration).mockResolvedValue(CALIBRATION)
    vi.mocked(api.getTradingLeaderboard).mockResolvedValue(LEADERBOARD)
    vi.mocked(api.getTradingPortfolio).mockResolvedValue({
      cash: 100, positions: [], equity: 3300, price_return_only: true,
      marks: [
        { mark_date: '2026-08-15', equity: 3000, spy_close: 555 },
        { mark_date: '2026-08-16', equity: 3300, spy_close: 560 },
        // A mark with no matching baseline point must be dropped, not
        // drawn against a phantom benchmark.
        { mark_date: '2026-08-17', equity: 3400, spy_close: null },
      ],
      spy_baseline: [
        { mark_date: '2026-08-15', value: 3000 },
        { mark_date: '2026-08-16', value: 3020 },
      ],
      spy_baseline_now: 3025,
    })
    render(<TrackRecordPanel />)
    await waitFor(() =>
      expect(screen.getByTestId('track-record-sparkline')).toBeInTheDocument(),
    )
    // Two joined points, two paths (equity solid, benchmark dashed).
    expect(
      screen.getByTestId('track-record-sparkline').querySelectorAll('path'),
    ).toHaveLength(2)
  })

  it('a failed portfolio read never hides the scoreboard', async () => {
    vi.mocked(api.getTradingCalibration).mockResolvedValue(CALIBRATION)
    vi.mocked(api.getTradingLeaderboard).mockResolvedValue(LEADERBOARD)
    vi.mocked(api.getTradingPortfolio).mockRejectedValue(new Error('502'))
    render(<TrackRecordPanel />)
    await waitFor(() =>
      expect(screen.getByTestId('track-record-panel')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('track-record-sparkline')).toBeNull()
  })
})

describe('LedgerScene mounts the panel', () => {
  const ready: WorkspaceObjectsState = {
    status: 'ready',
    objects: [],
    retry: vi.fn(),
  } as unknown as WorkspaceObjectsState

  it('shows the track record even before the first dossier entry', async () => {
    vi.mocked(api.getTradingCalibration).mockResolvedValue(CALIBRATION)
    vi.mocked(api.getTradingLeaderboard).mockResolvedValue(LEADERBOARD)
    render(<LedgerScene state={ready} />)
    await waitFor(() =>
      expect(screen.getByTestId('track-record-panel')).toBeInTheDocument(),
    )
  })
})
