import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceSceneFrame } from './WorkspaceSceneFrame'
import { IMPLEMENTED_WORKSPACE_SCENES } from '../../types/workspace.ts'

// Release 2 gives the frame its scene list instead of letting it decide.
// It used to hold its own copy of "only Home root has a House" while
// resolveWorkspaceScene held another; the list now comes from the one shared
// definition (scenesForDestination) and the frame's remaining job is to refuse
// a scene that is not on it.

const HOME = ['house', 'record'] as const
const SCHEME = ['record', 'bench', 'library', 'ledger'] as const

const content = {
  house: <div>House content</div>,
  record: <div>Record content</div>,
  bench: <div>Bench content</div>,
  field: <div>Field content</div>,
  library: <div>Library content</div>,
  ledger: <div>Ledger content</div>,
  atlas: <div>Atlas content</div>,
}

describe('WorkspaceSceneFrame', () => {
  it('renders House and Record choices at Home root', () => {
    render(
      <WorkspaceSceneFrame scene="house" scenes={HOME} onSelect={vi.fn()} content={content} />,
    )
    expect(screen.getByRole('button', { name: 'House' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument()
    expect(screen.getByText('House content')).toBeInTheDocument()
    expect(screen.queryByText('Record content')).not.toBeInTheDocument()
  })

  it('does not re-select the already active scene', () => {
    const onSelect = vi.fn()
    render(
      <WorkspaceSceneFrame scene="house" scenes={HOME} onSelect={onSelect} content={content} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'House' }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('routes a scene selection through the supplied callback', () => {
    const onSelect = vi.fn()
    render(
      <WorkspaceSceneFrame scene="house" scenes={HOME} onSelect={onSelect} content={content} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(onSelect).toHaveBeenCalledWith('record')
  })

  it('offers an ordinary room all four workroom scenes', () => {
    render(
      <WorkspaceSceneFrame scene="library" scenes={SCHEME} onSelect={vi.fn()} content={content} />,
    )
    for (const name of ['Record', 'Bench', 'Library', 'Ledger']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByText('Library content')).toBeInTheDocument()
  })

  it('keeps all seven scenes reachable through primary actions and More views', () => {
    render(
      <WorkspaceSceneFrame
        scene="record"
        scenes={IMPLEMENTED_WORKSPACE_SCENES}
        onSelect={vi.fn()}
        content={content}
      />,
    )
    fireEvent.click(screen.getByText('More views'))
    const controls = [
      ...screen.getAllByRole('button'),
      ...screen.getAllByRole('menuitem'),
    ]
    for (const name of ['House', 'Record', 'Bench', 'Field', 'Library', 'Ledger', 'Atlas']) {
      expect(controls.some((node) => node.textContent === name)).toBe(true)
    }
  })

  it('refuses a scene the destination does not offer', () => {
    // Defence in depth: mid-navigation the scene prop can lag the room, and a
    // House painted into a scheme room would be an empty household view.
    render(
      <WorkspaceSceneFrame scene="house" scenes={SCHEME} onSelect={vi.fn()} content={content} />,
    )
    expect(screen.getByText('Record content')).toBeInTheDocument()
    expect(screen.queryByText('House content')).not.toBeInTheDocument()
  })

  it('hides a one-item switcher — a single choice is not a choice', () => {
    render(
      <WorkspaceSceneFrame
        scene="record" scenes={['record'] as const} onSelect={vi.fn()} content={content}
      />,
    )
    expect(screen.queryByRole('navigation', { name: 'Room views' })).not.toBeInTheDocument()
    expect(screen.getByText('Record content')).toBeInTheDocument()
  })

  it('keeps the tray for a one-scene destination when instruments are present', () => {
    // A record-only Home branch still gets the presence lamp — the Console
    // keeps the tray alive even where a lone tab would not earn it.
    render(
      <WorkspaceSceneFrame
        scene="record" scenes={['record'] as const} onSelect={vi.fn()} content={content}
        instruments={<div>LAMP</div>}
      />,
    )
    expect(screen.getByRole('navigation', { name: 'Room views' })).toBeInTheDocument()
    expect(screen.getByText('LAMP')).toBeInTheDocument()
  })

  it('falls back to the default when a scene has no body yet', () => {
    render(
      <WorkspaceSceneFrame
        scene="ledger" scenes={SCHEME} onSelect={vi.fn()}
        content={{ record: <div>Record content</div> }}
      />,
    )
    expect(screen.getByText('Record content')).toBeInTheDocument()
  })
})
