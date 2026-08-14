import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AtlasScene } from './AtlasScene'
import type { AtlasState } from '../../../hooks/useAtlas.ts'
import type { AtlasNode, AtlasEdge } from '../../../types/atlas.ts'

function node(partial: Partial<AtlasNode> & Pick<AtlasNode, 'id' | 'kind' | 'room_id'>): AtlasNode {
  return {
    branch_id: null, title: partial.id, summary: '', status: '', due: false,
    created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
    ...partial,
  }
}

function ready(nodes: AtlasNode[], edges: AtlasEdge[] = []): AtlasState {
  return {
    status: 'ready',
    projection: { generated_at: 'x', nodes, edges },
    retry: vi.fn(),
  }
}

describe('AtlasScene', () => {
  it('shows loading, never empty, while in flight', () => {
    render(<AtlasScene state={{ status: 'loading' }} onNavigate={vi.fn()} />)
    expect(screen.getByTestId('scene-loading')).toBeInTheDocument()
  })

  it('shows unavailable, not an empty map, on failure', () => {
    render(
      <AtlasScene
        state={{ status: 'unavailable', error: 'boom', retry: vi.fn() }}
        onNavigate={vi.fn()}
      />,
    )
    expect(screen.getByTestId('scene-unavailable')).toBeInTheDocument()
  })

  it('teaches in the empty state when the caller belongs to no rooms with content', () => {
    render(<AtlasScene state={ready([])} onNavigate={vi.fn()} />)
    expect(screen.getByTestId('scene-empty')).toBeInTheDocument()
  })

  it('groups a branch and its artifact under their room', () => {
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' }),
      node({ id: 'branch:t1', kind: 'branch', room_id: 'r1', branch_id: 't1', title: 'A branch' }),
      node({ id: 'reading:a', kind: 'reading', room_id: 'r1', branch_id: 't1', title: 'An article' }),
    ]
    render(<AtlasScene state={ready(nodes)} onNavigate={vi.fn()} />)
    expect(screen.getByText('Trading Room')).toBeInTheDocument()
    expect(screen.getByText('A branch')).toBeInTheDocument()
    expect(screen.getByText('An article')).toBeInTheDocument()
  })

  it('navigates a room tap to the room, with no object axis', () => {
    const onNavigate = vi.fn()
    const nodes = [node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' })]
    render(<AtlasScene state={ready(nodes)} onNavigate={onNavigate} />)
    fireEvent.click(screen.getByText('Trading Room'))
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'r1' })
  })

  it('navigates a branch tap to the room and thread', () => {
    const onNavigate = vi.fn()
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' }),
      node({ id: 'branch:t1', kind: 'branch', room_id: 'r1', branch_id: 't1', title: 'A branch' }),
    ]
    render(<AtlasScene state={ready(nodes)} onNavigate={onNavigate} />)
    fireEvent.click(screen.getByText('A branch'))
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'r1', threadId: 't1' })
  })

  it('navigates an object-kind node tap through the object axis', () => {
    const onNavigate = vi.fn()
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' }),
      node({
        id: 'reading:a', kind: 'reading', room_id: 'r1', branch_id: null,
        title: 'An article',
      }),
    ]
    render(<AtlasScene state={ready(nodes)} onNavigate={onNavigate} />)
    // "An article" renders twice by design (the room tree AND the "Shared
    // sources" cross-cutting group over the same node) -- both must resolve
    // to the identical destination, so either instance proves the contract.
    const [first] = screen.getAllByText('An article')
    fireEvent.click(first)
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'r1', threadId: null, object: 'reading:a' })
  })

  it('surfaces unresolved work: open questions and due commitments, nothing else', () => {
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' }),
      node({ id: 'field_mark:a', kind: 'field_mark', room_id: 'r1', title: 'Open question' }),
      node({ id: 'commitment:due', kind: 'commitment', room_id: 'r1', title: 'Due commitment', due: true }),
      node({ id: 'commitment:notdue', kind: 'commitment', room_id: 'r1', title: 'Not due', due: false }),
    ]
    render(<AtlasScene state={ready(nodes)} onNavigate={vi.fn()} />)
    const group = screen.getByRole('region', { name: 'Unresolved work' })
    expect(group).toHaveTextContent('Open question')
    expect(group).toHaveTextContent('Due commitment')
    expect(group).not.toHaveTextContent('Not due')
  })

  it('marks a due commitment with a visible label, not colour alone', () => {
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Trading Room' }),
      node({ id: 'commitment:due', kind: 'commitment', room_id: 'r1', title: 'Due commitment', due: true }),
    ]
    render(<AtlasScene state={ready(nodes)} onNavigate={vi.fn()} />)
    // Appears twice by design: once in the room tree, once in the
    // "Unresolved work" cross-cutting group over the same projection.
    expect(screen.getAllByText('due').length).toBeGreaterThan(0)
  })

  it('lists an Echo citation whose target resolves to a real node', () => {
    const nodes = [
      node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Shared Room' }),
    ]
    const edges: AtlasEdge[] = [{
      kind: 'echo_citation',
      source: { entity: 'memories', id: 'm1', field: null },
      target: { entity: 'rooms', id: 'r1', field: null },
      label: 'a citation',
    }]
    render(<AtlasScene state={ready(nodes, edges)} onNavigate={vi.fn()} />)
    const group = screen.getByRole('region', { name: 'Echoes' })
    expect(group).toHaveTextContent('a citation')
  })

  it('does not render a live link for an Echo whose target is not a projected node', () => {
    const nodes = [node({ id: 'room:r1', kind: 'room', room_id: 'r1', title: 'Shared Room' })]
    const edges: AtlasEdge[] = [{
      kind: 'echo_citation',
      source: { entity: 'memories', id: 'm1', field: null },
      target: { entity: 'messages', id: 'msg1', field: null },
      label: 'unresolved target',
    }]
    render(<AtlasScene state={ready(nodes, edges)} onNavigate={vi.fn()} />)
    // Text is present, as plain text -- never inside a button, which would
    // read as an action that goes nowhere.
    const text = screen.getByText('unresolved target')
    expect(text.closest('button')).toBeNull()
  })
})
