import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WhatsNewPanel } from './WhatsNewPanel'
import { RELEASES, resetSeenCache, useUnreadReleases } from '../../lib/releases.ts'
import { api } from '../../lib/api.ts'

vi.mock('../../lib/api.ts', () => ({
  api: { getRoomCapabilities: vi.fn() },
}))

// The rule these fence: the prose says what was built, the badge says whether it
// is running HERE. A changelog that renders every line as shipped-and-live is
// the same instrument as the help modal that advertised five theses — it reads
// like a feature tour while half of it is dark on the reader's box.

type Caps = Awaited<ReturnType<typeof api.getRoomCapabilities>>

const caps = (jobs: Caps['jobs'] = []): Caps => ({
  thesis_bound: false,
  auto_interjection: true,
  interjection_turn_threshold: 8,
  scheduler_running: true,
  jobs,
})

/** Driven off the real data, so these keep testing the shipped list. */
const jobbed = RELEASES.find((release) => release.jobs && release.jobs.length > 0)!
const jobName = jobbed.jobs![0]
// Two entries may name the same job (world_watch: 'world-consumer' and 'fires');
// the badge under test is the newest entry's, which renders first.
const jobRow = async () => (await screen.findAllByText(jobName))[0].closest('li') as HTMLElement
const unjobbed = RELEASES.find((release) => !release.jobs)!

function entryRow(title: string): HTMLElement {
  return screen.getByText(title).closest('li.wn-entry') as HTMLElement
}

beforeEach(() => {
  resetSeenCache()
  window.localStorage.clear()
  vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps())
})

describe('WhatsNewPanel', () => {
  it('renders every entry, newest first', async () => {
    render(<WhatsNewPanel roomId="r1" />)
    const dates = (await screen.findAllByText(/^\d{4}-\d{2}-\d{2}$/))
      .map((node) => node.textContent ?? '')
    expect(dates).toEqual(RELEASES.map((release) => release.date))
    for (let i = 1; i < dates.length; i += 1) {
      expect(dates[i - 1] >= dates[i]).toBe(true)
    }
  })

  it('says a job is off when this deployment has it switched off', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(
      caps([{ name: jobName, enabled: false, interval_s: 900, daily_at: null }]),
    )
    render(<WhatsNewPanel roomId="r1" />)

    const row = await jobRow()
    expect(row.textContent).toMatch(/off/i)
    expect(row.textContent).not.toMatch(/live/i)
    expect(row.textContent).toMatch(/switched off/i)
  })

  it('says a job is absent, not off, when the scheduler does not have it', async () => {
    // Different facts: one is a flag someone can flip, one is not here at all.
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(caps([]))
    render(<WhatsNewPanel roomId="r1" />)
    const row = await jobRow()
    expect(row.textContent).toMatch(/absent/i)
    expect(row.textContent).toMatch(/not on this deployment/i)
  })

  it('says live only when the running scheduler says so', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(
      caps([{ name: jobName, enabled: true, interval_s: 900, daily_at: null }]),
    )
    render(<WhatsNewPanel roomId="r1" />)
    const row = await jobRow()
    expect(row.textContent).toMatch(/live/i)
    // DEPLOYMENT-scoped, and the wording is the assertion. This read "running
    // here", which told the reader the state was per-room; the capabilities
    // route builds its job list from the process-wide scheduler and answers
    // identically for every room. The false reading landed hardest on Home,
    // which is excluded from the Round by SQL while question_round is enabled —
    // "running here" under "a slate is drafted for this room" was wrong twice
    // in one row, on the room every user lands in.
    expect(row.textContent).toMatch(/running on this deployment/i)
    expect(row.textContent).not.toMatch(/running here/i)
  })

  it('gives an entry with no verifiable job no badge at all', async () => {
    vi.mocked(api.getRoomCapabilities).mockResolvedValue(
      caps([{ name: jobName, enabled: true, interval_s: 900, daily_at: null }]),
    )
    render(<WhatsNewPanel roomId="r1" />)
    await jobRow()
    // A green badge it did not earn would be exactly the lie this panel exists
    // to prevent — so a UI-only release gets nothing rather than something.
    expect(entryRow(unjobbed.title).querySelector('.wn-state')).toBeNull()
  })

  it('claims nothing is live when the room could not be read', async () => {
    vi.mocked(api.getRoomCapabilities).mockRejectedValue(new Error('nope'))
    render(<WhatsNewPanel roomId="r1" />)
    expect(await screen.findByTestId('wn-unknown')).toBeInTheDocument()
    expect(screen.queryByText(jobName)).not.toBeInTheDocument()
    expect(document.querySelector('.wn-state')).toBeNull()
  })

  it('explains a hard word in place', async () => {
    // The NEWEST release must carry a gloss -- that is the whole discipline.
    // Loosened 2026-08-26 to 'any release', which passes forever; restored.
    const marked = /\[\[([^\]|]+)\|([^\]]+)\]\]/.exec(RELEASES[0].body)
    expect(marked).not.toBeNull()
    if (!marked) throw new Error('the newest release has no glossary marker')
    render(<WhatsNewPanel roomId="r1" />)
    const trigger = await screen.findByRole('button', { name: marked[2] })
    fireEvent.click(trigger)
    expect(await screen.findByRole('note')).toBeInTheDocument()
  })
})

describe('the unread badge', () => {
  function Badge() {
    return <span data-testid="count">{useUnreadReleases()}</span>
  }

  function Harness() {
    return (
      <>
        <Badge />
        <WhatsNewPanel roomId="r1" />
      </>
    )
  }

  /** The badge AFTER the panel — so the panel's effect marks everything seen
   *  before the badge has had a chance to subscribe. Effects run in tree order,
   *  so this ordering, and only this one, exercises the race. The orchestrator
   *  chooses the placement, so it must work in both. */
  function LateBadge() {
    return (
      <>
        <WhatsNewPanel roomId="r1" />
        <Badge />
      </>
    )
  }

  it('counts every entry on a first run', () => {
    render(<Badge />)
    expect(screen.getByTestId('count').textContent).toBe(String(RELEASES.length))
  })

  it('reads 0 once the panel has been opened, without the marks vanishing', async () => {
    render(<Harness />)
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('0'))
    // …and the "new" marks stay put for the person currently reading them.
    expect(screen.getAllByText('new').length).toBe(RELEASES.length)
  })

  it('catches up even when the panel marked everything seen before it subscribed', async () => {
    // The failure this exists for: a badge that renders its count once, misses
    // the event because it had not subscribed yet, and then sits stale until
    // something else happens to remount it. Rendering order is the
    // orchestrator's choice, not ours, so it cannot be the thing that decides
    // whether the badge is correct.
    render(<LateBadge />)
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('0'))
  })

  it('shows nothing new on the next open', async () => {
    const first = render(<Harness />)
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('0'))
    first.unmount()

    render(<Harness />)
    expect(await screen.findByTestId('whats-new')).toBeInTheDocument()
    expect(screen.queryByText('new')).not.toBeInTheDocument()
    expect(screen.getByTestId('count').textContent).toBe('0')
  })

  it('survives a localStorage that throws on every access', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('site data blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('site data blocked')
    })
    render(<Harness />)
    // Renders, does not badge, and cannot get stuck badging.
    expect(await screen.findByTestId('whats-new')).toBeInTheDocument()
    expect(screen.getByTestId('count').textContent).toBe('0')
    expect(screen.queryByText('new')).not.toBeInTheDocument()
  })
})
