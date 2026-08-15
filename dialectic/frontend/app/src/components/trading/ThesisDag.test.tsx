import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ThesisDag } from './ThesisDag'
import type { ThesisStructure } from '../../types/trading'

// Small fixture: 4 nodes across 2 phases, 3 edges with mechanisms. Labels
// and mechanisms are kept short enough to render without ellipsis so exact
// text queries stay meaningful.
const structure: ThesisStructure = {
  id: 'thesis-1',
  meta: { title: 'Test thesis' },
  nodes: [
    { id: 'n1', label: 'Oil spikes', type: 'event', phase: 1, state: 'monitoring', x: 0, y: 0 },
    { id: 'n2', label: 'Crude $95', type: 'price', phase: 1, state: 'approaching', x: 0, y: 120 },
    { id: 'n3', label: 'Fed pauses', type: 'policy', phase: 2, state: 'fired', x: 280, y: 0 },
    { id: 'n4', label: 'Recession bets', type: 'market', phase: 2, state: 'monitoring', x: 280, y: 120 },
  ],
  edges: [
    { source: 'n1', target: 'n2', mechanism: 'inventory shock', lag: '2d', strength: 0.8 },
    { source: 'n2', target: 'n3', mechanism: 'price forces policy', lag: '1w', strength: 0.6 },
    { source: 'n1', target: 'n4', mechanism: 'risk repricing', lag: '3d', strength: 0.4 },
  ],
  scenarios: [],
}

describe('ThesisDag', () => {
  it('renders all nodes and edge mechanism labels', () => {
    render(<ThesisDag structure={structure} />)
    // Each label appears twice by design: once as the node's visible <text>,
    // once in its <title> (the full-text tooltip for ellipsized labels) --
    // either instance proves the node rendered.
    expect(screen.getAllByText('Oil spikes').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Crude $95').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Fed pauses').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Recession bets').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/inventory shock/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/price forces policy/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/risk repricing/).length).toBeGreaterThan(0)
  })

  it('overrides authored state with a live reading; a node missing from nodeStates is dimmed', () => {
    render(<ThesisDag structure={structure} nodeStates={{ n1: 'fired', n2: 'approaching' }} />)

    // n1 authored 'monitoring' but live 'fired' -> renders as fired.
    const n1 = screen.getByRole('button', { name: /Oil spikes/ })
    expect(n1.getAttribute('class')).toContain('thesis-dag-node--fired')
    expect(n1.getAttribute('aria-label')).toContain('fired')

    // n3 has no entry in nodeStates -> dimmed (authored-only, no live reading).
    const n3 = screen.getByRole('button', { name: /Fed pauses/ })
    expect(n3.getAttribute('class')).toContain('thesis-dag-node--dimmed')
    expect(n3.getAttribute('aria-label')).toContain('no live reading')
  })

  it('opens the detail card on Enter, closes on Escape and on the close button', () => {
    render(<ThesisDag structure={structure} />)
    const n1 = screen.getByRole('button', { name: /Oil spikes/ })
    n1.focus()
    fireEvent.keyDown(n1, { key: 'Enter' })

    const card = screen.getByRole('region', { name: /Oil spikes detail/i })
    expect(card).toHaveTextContent('Oil spikes')

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('region', { name: /Oil spikes detail/i })).not.toBeInTheDocument()

    // Space also opens it; the close button also closes it.
    fireEvent.keyDown(n1, { key: ' ' })
    expect(screen.getByRole('region', { name: /Oil spikes detail/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /close detail/i }))
    expect(screen.queryByRole('region', { name: /Oil spikes detail/i })).not.toBeInTheDocument()
  })

  it('lists an unknown snapshot node id in the footnote without crashing', () => {
    render(<ThesisDag structure={structure} nodeStates={{ n1: 'fired', ghost: 'approaching' }} />)
    const footnote = screen.getByText(/unknown node/i)
    expect(footnote).toHaveTextContent('ghost')
  })

  it('shows a stale badge without hiding node data', () => {
    render(<ThesisDag structure={structure} nodeStates={{ n1: 'fired' }} stale />)
    expect(screen.getByText(/stale snapshot/i)).toBeInTheDocument()
    expect(screen.getAllByText('Oil spikes').length).toBeGreaterThan(0)
  })
})
