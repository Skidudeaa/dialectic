import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAppStore } from '../../stores/appStore.ts'
import { RoomHeader } from './RoomHeader'


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
