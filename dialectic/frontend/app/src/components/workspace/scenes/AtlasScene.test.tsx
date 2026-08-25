import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AtlasScene } from './AtlasScene'
import type { AtlasState } from '../../../hooks/useAtlas.ts'
import type { AtlasNode, AtlasEdge } from '../../../types/atlas.ts'
import type { GeoScope } from '../../../types/geo.ts'

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
    projection: { generated_at: 'x', nodes, edges, scopes: [] },
    retry: vi.fn(),
  }
}

describe('AtlasScene', () => {
  it('shows loading, never empty, while in flight', () => {
    render(<AtlasScene state={{ status: 'loading', retry: vi.fn() }} onNavigate={vi.fn()} />)
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

// ---------------------------------------------------------------------------
// World Lens: the second mode of the same projection
// ---------------------------------------------------------------------------

vi.mock('../world/WorldView', () => ({
  default: (props: { scopes: GeoScope[]; onSelect: (scope: GeoScope) => void }) => (
    <div data-testid="world-view-mock">
      globe:{props.scopes.length}
      <button type="button" onClick={() => props.onSelect(props.scopes[0])}>Select globe scope</button>
    </div>
  ),
}))

function readyWithScopes(nodes: AtlasNode[], scopes: GeoScope[]): AtlasState {
  return {
    status: 'ready',
    projection: { generated_at: 'x', nodes, edges: [], scopes },
    retry: vi.fn(),
  }
}

const hormuzScope: GeoScope = {
  id: 'geo_scope:s1', room_id: 'room-h',
  subject: { entity: 'rooms', id: 'room-h' },
  kind: 'polygon' as const,
  geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 26]]] },
  label: 'Strait of Hormuz (approx.)', authority: 'human_confirmed' as const,
  provenance: { provider: 'human', acquisition: 'human', credit: 'sketch' },
  source_state: 'ok' as const, revision_action: 'place', review_note: null, review_state: 'accepted',
  freshness: { state: 'current', observed_at: null, retrieved_at: '2026-08-25T00:00:00Z', expires_at: null },
  centroid: [56, 26.5] as [number, number],
  retrieved_at: '2026-08-25T00:00:00Z', created_at: '2026-08-25T00:00:00Z',
}

describe('AtlasScene / World', () => {
  const rooms = [node({ id: 'room:room-h', kind: 'room', room_id: 'room-h', title: 'Hormuz' })]

  it('is House by default and offers the World toggle only when a writer is given', () => {
    const { rerender } = render(<AtlasScene state={readyWithScopes(rooms, [hormuzScope])} onNavigate={vi.fn()} />)
    expect(screen.queryByRole('group', { name: 'Atlas mode' })).toBeNull()
    expect(screen.queryByTestId('world-view-mock')).toBeNull()
    rerender(<AtlasScene state={readyWithScopes(rooms, [hormuzScope])} onNavigate={vi.fn()} onView={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'House' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByTestId('world-view-mock')).toBeNull()
  })

  it('a World tap is a navigate through the one writer, never a local state', () => {
    const onView = vi.fn()
    render(<AtlasScene state={readyWithScopes(rooms, [hormuzScope])} onNavigate={vi.fn()} onView={onView} />)
    fireEvent.click(screen.getByRole('button', { name: 'World' }))
    expect(onView).toHaveBeenCalledWith('world', 'push')
  })

  it('World mode keeps the complete list under the globe and lists every scope as text', async () => {
    const onNavigate = vi.fn()
    render(
      <AtlasScene
        state={readyWithScopes(rooms, [hormuzScope])}
        onNavigate={onNavigate}
        view="world"
        onView={vi.fn()}
      />,
    )
    expect(await screen.findByTestId('world-view-mock')).toHaveTextContent('globe:1')
    // The House tree is still there -- the globe never replaces it.
    expect(screen.getByRole('list', { name: 'Rooms' })).toBeInTheDocument()
    // And the scope is readable without WebGL, with its authority and state.
    const row = screen.getByRole('button', { name: /Strait of Hormuz/ })
    expect(row).toHaveTextContent('confirmed')
    expect(row).toHaveTextContent('live')
    fireEvent.click(row)
    expect(onNavigate).toHaveBeenCalledWith({ roomId: 'room-h', object: 'geo_scope:s1' })

    fireEvent.click(screen.getByRole('button', { name: 'Select globe scope' }))
    expect(onNavigate).toHaveBeenLastCalledWith({ roomId: 'room-h', object: 'geo_scope:s1' })
  })

  it('keeps room, reading, and message scopes inspectable in House without loading the globe', () => {
    const onNavigate = vi.fn()
    const scopes = [
      { ...hormuzScope, id: 'geo_scope:room', label: 'Room placement' },
      { ...hormuzScope, id: 'geo_scope:reading', label: 'Reading placement', subject: { entity: 'reading_items', id: 'read-1' } },
      { ...hormuzScope, id: 'geo_scope:message', label: 'Message placement', subject: { entity: 'messages', id: 'msg-1' } },
    ]
    render(
      <AtlasScene
        state={readyWithScopes(rooms, scopes)}
        onNavigate={onNavigate}
        onView={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('world-view-mock')).toBeNull()
    for (const [label, id] of [
      ['Room placement', 'geo_scope:room'],
      ['Reading placement', 'geo_scope:reading'],
      ['Message placement', 'geo_scope:message'],
    ]) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(label) }))
      expect(onNavigate).toHaveBeenLastCalledWith({ roomId: 'room-h', object: id })
    }
  })

  it('a proposed scope is labelled as such in the list', async () => {
    render(
      <AtlasScene
        state={readyWithScopes(rooms, [{ ...hormuzScope, authority: 'machine_proposed', label: 'Guess' }])}
        onNavigate={vi.fn()}
        view="world"
        onView={vi.fn()}
      />,
    )
    await screen.findByTestId('world-view-mock')
    expect(screen.getByRole('button', { name: /Guess/ })).toHaveTextContent('proposed')
  })
})
