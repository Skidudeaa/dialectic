import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { HelpDialog } from './HelpDialog'
import { markAllSeen, resetSeenCache } from '../../lib/releases.ts'
import { api } from '../../lib/api.ts'

vi.mock('../../lib/api.ts', () => ({
  api: { getRoomCapabilities: vi.fn() },
}))

// The one door to every explanation in the product. What these fence is that
// the door OPENS ON THE THING IT ADVERTISES: the header badge counts unread
// release entries, so a badge that opens the capability map instead is a badge
// lying about what it counts.

beforeEach(() => {
  resetSeenCache()
  window.localStorage.clear()
  vi.mocked(api.getRoomCapabilities).mockResolvedValue({
    thesis_bound: false,
    auto_interjection: true,
    interjection_turn_threshold: 8,
    scheduler_running: true,
    jobs: [],
  })
})

describe('HelpDialog', () => {
  it('offers both shelves as real tabs', () => {
    render(<HelpDialog roomId="r1" onClose={() => {}} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(2)
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(tabs[1].getAttribute('aria-selected')).toBe('false')
  })

  it('opens on the capability map by default', () => {
    render(<HelpDialog roomId="r1" onClose={() => {}} />)
    expect(screen.getByTestId('capability-map')).toBeTruthy()
    expect(screen.queryByTestId('whats-new')).toBeNull()
  })

  it('opens straight onto What changed when asked to', () => {
    // THE BADGE CONTRACT. RoomHeader passes 'new' when the unread count is
    // non-zero; without this the badge would count one thing and open another.
    render(<HelpDialog roomId="r1" initialTab="new" onClose={() => {}} />)
    expect(screen.getByTestId('whats-new')).toBeTruthy()
    expect(screen.queryByTestId('capability-map')).toBeNull()
  })

  it('switches shelves on a tab press, heading and all', () => {
    render(<HelpDialog roomId="r1" onClose={() => {}} />)
    expect(screen.getByRole('heading', { name: /what can this room do/i })).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: /what changed/i }))
    expect(screen.getByTestId('whats-new')).toBeTruthy()
    expect(screen.getByRole('heading', { name: /^what changed$/i })).toBeTruthy()
  })

  it('shows the unread count on the tab, as text and not a bare dot', () => {
    // Colour-only or shape-only signals are barred here — the accessible name
    // has to carry the number, the way SceneSwitcher's signals do.
    render(<HelpDialog roomId="r1" onClose={() => {}} />)
    const tab = screen.getByRole('tab', { name: /what changed/i })
    expect(tab.textContent).toMatch(/\d/)
  })

  it('drops the count once the reader has caught up', () => {
    markAllSeen()
    render(<HelpDialog roomId="r1" onClose={() => {}} />)
    const tab = screen.getByRole('tab', { name: /what changed/i })
    expect(tab.textContent).not.toMatch(/\d/)
  })

  it('closes on Escape', () => {
    const onClose = vi.fn()
    render(<HelpDialog roomId="r1" onClose={onClose} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})
