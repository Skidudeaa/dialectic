import { render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useAppStore } from '../../stores/appStore.ts'
import { AppLayout } from './AppLayout'


afterEach(() => {
  useAppStore.getState().logout()
})


describe('AppLayout', () => {
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
