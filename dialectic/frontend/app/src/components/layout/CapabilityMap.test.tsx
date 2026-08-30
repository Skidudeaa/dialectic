import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CapabilityMap } from './CapabilityMap'
import { api } from '../../lib/api.ts'

vi.mock('../../lib/api.ts', () => ({
  api: { getRoomCapabilities: vi.fn() },
}))

// The help modal advertised a daily rhythm of jobs that are mostly OFF in this
// deployment. These tests fence the reason the map replaced it: it must be able
// to say "off", and it must refuse to claim anything it could not read.

type Caps = Awaited<ReturnType<typeof api.getRoomCapabilities>>

const caps = (over: Partial<Caps> = {}): Caps => ({
  thesis_bound: false,
  auto_interjection: true,
  interjection_turn_threshold: 4,
  scheduler_running: true,
  jobs: [],
  ...over,
})

describe('CapabilityMap', () => {
  beforeEach(() => vi.clearAllMocks())

  it('says a job is off when it is off', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [
        { name: 'wire_watch', enabled: false, interval_s: 900, daily_at: null },
        { name: 'morning_brief', enabled: true, interval_s: 86400, daily_at: '07:00' },
      ],
    }))
    render(<CapabilityMap roomId="r1" />)

    const wire = await screen.findByText(/The wire/)
    // Not colour alone — the word "off" has to be in the row (§17.4).
    expect(wire.closest('li')?.textContent).toMatch(/off/i)
    expect(screen.getByText(/Morning brief/).closest('li')?.textContent).toMatch(/on/i)
  })

  it('shows each job at its real cadence', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [{ name: 'morning_brief', enabled: true, interval_s: 86400, daily_at: '07:00' }],
    }))
    render(<CapabilityMap roomId="r1" />)
    expect((await screen.findByText(/Morning brief/)).closest('li')?.textContent)
      .toMatch(/daily 07:00/)
  })

  it('claims nothing about a room it could not read', async () => {
    vi.mocked(api.getRoomCapabilities).mockRejectedValue(new Error('nope'))
    render(<CapabilityMap roomId="r1" />)
    // The failure mode that matters: silently showing defaults would tell the
    // reader auto-interjection is ON when we have no idea.
    expect(await screen.findByTestId('capability-unknown')).toBeInTheDocument()
    expect(screen.queryByText(/may join without being summoned/)).not.toBeInTheDocument()
  })

  it('tells the truth about a room with no thesis', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({ thesis_bound: false }))
    render(<CapabilityMap roomId="r1" />)
    expect(await screen.findByText(/No thesis here yet/)).toBeInTheDocument()
  })

  it('says so when nothing is running at all', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(
      caps({ scheduler_running: false, jobs: [] }))
    render(<CapabilityMap roomId="r1" />)
    expect(await screen.findByText(/No background work is running/)).toBeInTheDocument()
  })

  it('renders a job name it has no copy for rather than dropping it', async () => {
    // A job added on the backend must not silently vanish from the map.
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [{ name: 'brand_new_job', enabled: true, interval_s: 600, daily_at: null }],
    }))
    render(<CapabilityMap roomId="r1" />)
    await waitFor(() => expect(screen.getByText('brand_new_job')).toBeInTheDocument())
  })

  // ── the six jobs that had no copy at all until 2026-08-21 ────────────────

  it('names every job the scheduler runs, never its snake_case', async () => {
    // tests/test_capability_copy_contract.py is the fence that keeps JOB_COPY
    // complete against the real roster; this is what "complete" buys the
    // reader. Six of fifteen rendered as raw identifiers before this — the
    // newest six, including the Round two days before its first fire.
    const newest = [
      'question_round', 'house_forecast_sweep', 'round_close_watch',
      'rss_wire', 'congress_watch', 'field_inference',
    ]
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: newest.map((name) => ({
        name, enabled: true, interval_s: 3600, daily_at: null,
      })),
    }))
    render(<CapabilityMap roomId="r1" />)

    await screen.findByRole('button', { name: 'The Round' })
    for (const name of newest) {
      expect(screen.queryByText(name)).not.toBeInTheDocument()
    }
    for (const label of ['The house forecast', 'Watchlist feeds',
      'Disclosures', 'Field marks']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('does not call the Round daily when it only fires on Sundays', async () => {
    // THE DEFECT: question_round is registered daily_at="09:00" because the
    // scheduler has no weekly cadence — is_round_day() returns immediately on
    // the other six mornings. Rendering the Job's own field printed
    // "daily 09:00", which the reader has no way to check.
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [{ name: 'question_round', enabled: true, interval_s: 86400, daily_at: '09:00' }],
    }))
    render(<CapabilityMap roomId="r1" />)

    const row = (await screen.findByRole('button', { name: 'The Round' })).closest('li')
    expect(row?.textContent).toMatch(/Sundays 09:00/)
    expect(row?.textContent).not.toMatch(/daily/i)
  })

  it('still reads the scheduler for every job with no override', async () => {
    // The override is one job's exception, not a licence to author cadences.
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [
        { name: 'congress_watch', enabled: false, interval_s: 3600, daily_at: null },
        { name: 'field_inference', enabled: true, interval_s: 1800, daily_at: null },
      ],
    }))
    render(<CapabilityMap roomId="r1" />)
    expect((await screen.findByText('Disclosures')).closest('li')?.textContent)
      .toMatch(/every 1h/)
    expect(screen.getByText('Field marks').closest('li')?.textContent)
      .toMatch(/every 30 min/)
  })

  // ── World Lens: the consumer (2026-08-30) ────────────────────────────────

  it('names World watch, and gives Live world signals its new off-reason', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [
        { name: 'world_watch', enabled: false, interval_s: 300, daily_at: null },
        { name: 'world_signals', enabled: false, interval_s: 120, daily_at: null },
      ],
    }))
    render(<CapabilityMap roomId="r1" />)

    const watchRow = (await screen.findByText('World watch')).closest('li')
    expect(watchRow?.textContent).toMatch(/two turns a day at most/)
    expect(watchRow?.textContent).toMatch(/no room has bound geography to the thesis yet/)

    const signalsRow = screen.getByText('Live world signals').closest('li')
    expect(signalsRow?.textContent).toMatch(/stays dark only when no room has placed geography/)
  })

  // ── the help screen defines its own vocabulary ───────────────────────────

  it('defines a term on tap rather than leaving it as jargon', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [{ name: 'question_round', enabled: true, interval_s: 86400, daily_at: '09:00' }],
    }))
    render(<CapabilityMap roomId="r1" />)

    const trigger = await screen.findByRole('button', { name: 'The Round' })
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    trigger.click()
    expect(await screen.findByRole('note')).toHaveTextContent(/named resolution source/)
  })

  it('carries the whole glossary, so no hard word is defined nowhere', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps())
    render(<CapabilityMap roomId="r1" />)
    await screen.findByText(/Every word this product uses/)
    // The definition that gets quoted at people and never explained.
    expect(screen.getByText(/0 is perfect, 1 is perfectly wrong/)).toBeInTheDocument()
    expect(screen.getByText('Brier score')).toBeInTheDocument()
  })

  it('says WHY a job that ships dark is off, and only while it is off', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps({
      jobs: [
        { name: 'rss_wire', enabled: false, interval_s: 900, daily_at: null },
        { name: 'world_signals', enabled: true, interval_s: 120, daily_at: null },
      ],
    }))
    render(<CapabilityMap roomId="r1" />)
    const rss = await screen.findByText(/Watchlist feeds/)
    expect(rss.closest('li')?.textContent).toMatch(/no room lists a feed/)
    expect(screen.getByText(/Live world signals/).closest('li')?.textContent)
      .not.toMatch(/nothing reads/)
  })
})
