import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAppStore } from '../../stores/appStore.ts'
import { RoomHeader } from './RoomHeader'
import { markAllSeen, resetSeenCache } from '../../lib/releases.ts'


const props = {
  roomName: 'Scheme room',
  threads: [],
  activeThreadId: null,
  onThreadChange: vi.fn(),
  onProtocolClick: vi.fn(),
  onSettingsClick: vi.fn(),
  onSearchClick: vi.fn(),
  onHelpClick: vi.fn(),
  connected: true,
  isHome: false,
  onHomeClick: vi.fn(),
}


afterEach(() => {
  useAppStore.getState().logout()
})


describe('RoomHeader rail controls', () => {
  it('toggles the explicit desktop context column', () => {
    render(<RoomHeader {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open desktop context panel' }))
    expect(useAppStore.getState().rightPanelOpen).toBe(true)
    expect(screen.getByRole('button', { name: 'Close desktop context panel' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('uses the independent overlay state for the compact context drawer', () => {
    render(<RoomHeader {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open context drawer' }))
    expect(useAppStore.getState().mobileDrawer).toBe('panel')
    expect(useAppStore.getState().rightPanelOpen).toBe(false)
  })
})


describe('the help door', () => {
  beforeEach(() => {
    resetSeenCache()
    window.localStorage.clear()
  })

  it('keeps a name when the label is hidden', () => {
    // THE DEFECT THIS PINS. `.btn-label` is `display: none` under 600px, and
    // this button's mark used to be a chevron-down — so a phone got a bare
    // unlabelled "⌄" as the ONLY route to every explanation in the product. It
    // read as "expand something", not "explain this". CSS cannot be asserted in
    // jsdom, so the fence is the accessible name, which is what a reader who
    // cannot see the glyph actually gets, at every width.
    render(<RoomHeader {...props} />)
    const help = screen.getByRole('button', { name: /^help/i })
    expect(help.getAttribute('aria-label')).toBeTruthy()
  })

  it('opens the capability map when nothing has shipped since last look', () => {
    markAllSeen()
    const onHelpClick = vi.fn()
    render(<RoomHeader {...props} onHelpClick={onHelpClick} />)
    fireEvent.click(screen.getByRole('button', { name: /^help/i }))
    expect(onHelpClick).toHaveBeenCalledWith('room')
  })

  it('opens What changed, and says how many, when entries are unread', () => {
    // A badge that opens a dialog showing something else is a badge that lies
    // about what it is counting.
    const onHelpClick = vi.fn()
    render(<RoomHeader {...props} onHelpClick={onHelpClick} />)
    const help = screen.getByRole('button', { name: /new since you last looked/i })
    expect(help.textContent).toMatch(/\d/)
    fireEvent.click(help)
    expect(onHelpClick).toHaveBeenCalledWith('new')
  })
})
