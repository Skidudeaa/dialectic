import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
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

describe('normalizeLayout (via render)', () => {
  it('restacks the baked-diagonal fallback per phase column', () => {
    // Real production signature: every x exactly on the (phase-1)*280+100
    // grid, y a global-index diagonal (60, 180, 300, ...). The component
    // must restack y per phase so two same-phase nodes sit at 60 and 180,
    // not 60 and 300.
    const diagonal: ThesisStructure = {
      id: 'diag',
      meta: { title: 'Diagonal' },
      nodes: [
        { id: 'a', label: 'A', type: 'event', phase: 1, state: 'monitoring', x: 100, y: 60 },
        { id: 'b', label: 'B', type: 'event', phase: 1, state: 'monitoring', x: 100, y: 180 },
        { id: 'c', label: 'C', type: 'event', phase: 2, state: 'monitoring', x: 380, y: 300 },
      ],
      edges: [],
      scenarios: [],
    }
    render(<ThesisDag structure={diagonal} />)
    const c = screen.getByRole('button', { name: /^C/ })
    // Phase-2's first node restacks to row 0 (y=60), not the diagonal 300.
    expect(c.getAttribute('transform')).toBe('translate(380, 60)')
    const b = screen.getByRole('button', { name: /^B/ })
    expect(b.getAttribute('transform')).toBe('translate(100, 180)')
  })

  it('leaves authored (off-grid) layouts untouched', () => {
    const authored: ThesisStructure = {
      id: 'auth',
      meta: { title: 'Authored' },
      nodes: [
        { id: 'a', label: 'A', type: 'event', phase: 1, state: 'monitoring', x: 40, y: 500 },
      ],
      edges: [],
      scenarios: [],
    }
    render(<ThesisDag structure={authored} />)
    const a = screen.getByRole('button', { name: /^A/ })
    expect(a.getAttribute('transform')).toBe('translate(40, 500)')
  })
})

// ── The working surface's affordances (2026-09-02) ───────────────────────
describe('ThesisDag on the surface', () => {
  const words = { n1: { authorName: 'Dan', createdAt: new Date().toISOString(), quote: 'For the first time on record' } }

  it('renders a human word under a spoken node and "quiet" under the rest', () => {
    render(<ThesisDag structure={structure} humanWords={words} />)
    expect(screen.getAllByText(/For the first time/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('quiet').length).toBe(3)
    expect(screen.getByRole('button', { name: /Oil spikes.*Dan spoke on it/ })).toBeInTheDocument()
  })

  it('is controlled by focusedNodeId, reports focus, and offers verbs on the focused node', () => {
    const onFocusNode = vi.fn()
    const run = vi.fn()
    const { rerender } = render(
      <ThesisDag structure={structure} focusedNodeId={null} onFocusNode={onFocusNode} verbs={[{ label: 'Speak to it', run }]} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /^Crude \$95/ }))
    expect(onFocusNode).toHaveBeenCalledWith(expect.objectContaining({ id: 'n2' }))
    // Controlled: nothing opens until the parent installs the focus.
    expect(screen.queryByRole('region', { name: /detail/ })).toBeNull()
    rerender(
      <ThesisDag structure={structure} focusedNodeId="n2" onFocusNode={onFocusNode} verbs={[{ label: 'Speak to it', run }]} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Speak to it' }))
    expect(run).toHaveBeenCalledWith(expect.objectContaining({ id: 'n2' }))
  })

  it('accepts a dropped ref on a node and reports an edge tap', () => {
    const onDropRef = vi.fn()
    const onEdgeSelect = vi.fn()
    const { container } = render(<ThesisDag structure={structure} onDropRef={onDropRef} onEdgeSelect={onEdgeSelect} />)
    const node = screen.getByRole('button', { name: /^Fed pauses/ })
    const ref = { entity: 'world_observations', id: 'o1', label: 'fire cell' }
    const dataTransfer = {
      types: ['application/x-dialectic-ref'],
      getData: (mime: string) => (mime === 'application/x-dialectic-ref' ? JSON.stringify(ref) : ''),
      dropEffect: 'none',
    }
    fireEvent.dragOver(node, { dataTransfer })
    fireEvent.drop(node, { dataTransfer })
    expect(onDropRef).toHaveBeenCalledWith(expect.objectContaining({ id: 'n3' }), ref)
    const edge = container.querySelector('.thesis-dag-edge--clickable') as SVGGElement
    fireEvent.click(edge)
    expect(onEdgeSelect).toHaveBeenCalledWith(expect.objectContaining({ mechanism: 'inventory shock' }))
  })
})
