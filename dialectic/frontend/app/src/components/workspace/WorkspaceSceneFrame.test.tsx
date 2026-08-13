import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceSceneFrame } from './WorkspaceSceneFrame'

describe('WorkspaceSceneFrame', () => {
  it('renders House and Record choices at Home root', () => {
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot
        onSelect={vi.fn()}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    expect(screen.getByRole('button', { name: 'House' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
    expect(screen.getByText('House content')).toBeInTheDocument()
    expect(screen.queryByText('Record content')).not.toBeInTheDocument()
  })

  it('does not re-select the already active scene', () => {
    const onSelect = vi.fn()
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot
        onSelect={onSelect}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'House' }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('routes a Home scene selection through the supplied callback', () => {
    const onSelect = vi.fn()
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot
        onSelect={onSelect}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(onSelect).toHaveBeenCalledWith('record')
  })

  it('forces non-Home destinations to Record and hides a one-item switcher', () => {
    render(
      <WorkspaceSceneFrame
        scene="house"
        isHomeRoot={false}
        onSelect={vi.fn()}
        house={<div>House content</div>}
        record={<div>Record content</div>}
      />,
    )

    expect(screen.queryByRole('navigation', { name: 'Room views' })).not.toBeInTheDocument()
    expect(screen.getByText('Record content')).toBeInTheDocument()
    expect(screen.queryByText('House content')).not.toBeInTheDocument()
  })
})
