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
})
