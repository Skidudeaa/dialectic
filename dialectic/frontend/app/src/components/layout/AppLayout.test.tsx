import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAppStore } from '../../stores/appStore.ts'
import { AppLayout } from './AppLayout'


afterEach(() => {
  useAppStore.getState().logout()
  vi.unstubAllGlobals()
})


describe('AppLayout', () => {
  it('fits Surface to keyboard space, leaves pinch zoom alone, and cleans up on scene exit', () => {
    const viewport = Object.assign(new EventTarget(), { height: 768, offsetTop: 0, scale: 1 })
    vi.stubGlobal('visualViewport', viewport)
    const props = { sidebar: <div />, main: <div />, rightPanel: <div /> }
    const { container, rerender } = render(<AppLayout {...props} workspaceScene="surface" />)
    const layout = container.firstChild as HTMLElement
    expect(layout.style.height).toBe('768px')
    viewport.height = 420
    viewport.dispatchEvent(new Event('resize'))
    expect(layout.style.height).toBe('420px')
    expect(layout).toHaveClass('surface-short')
    viewport.scale = 2
    viewport.height = 210
    viewport.dispatchEvent(new Event('resize'))
    expect(layout.style.height).toBe('420px')
    rerender(<AppLayout {...props} workspaceScene="record" />)
    expect(layout.style.height).toBe('')
    expect(layout).not.toHaveClass('surface-short')
    viewport.scale = 1
    viewport.dispatchEvent(new Event('resize'))
    expect(layout.style.height).toBe('')
  })

  it('does not reserve a desktop context column while the panel is closed', () => {
    useAppStore.setState({ rightPanelOpen: false })
    const { container } = render(
      <AppLayout sidebar={<div />} main={<div />} rightPanel={<div />} />,
    )
    expect(container.firstChild).toHaveClass('right-panel-closed')
  })

  it('marks the desktop context column open explicitly', () => {
    useAppStore.setState({ rightPanelOpen: true })
    const { container } = render(
      <AppLayout sidebar={<div />} main={<div />} rightPanel={<div />} />,
    )
    expect(container.firstChild).toHaveClass('right-panel-open')
  })
})
