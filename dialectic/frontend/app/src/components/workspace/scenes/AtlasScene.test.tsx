import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AtlasScene } from './AtlasScene'
import { api } from '../../../lib/api.ts'
import type { AtlasState } from '../../../hooks/useAtlas.ts'
import type {
  AtlasEdge,
  AtlasGeoScope,
  AtlasNode,
  CausalGeoBinding,
} from '../../../types/atlas.ts'
import type { GeoScope, WorldSignal } from '../../../types/geo.ts'

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
  default: (props: {
    scopes: GeoScope[]
    signals: WorldSignal[]
    selectedScopeId?: string | null
    onSelect: (scope: GeoScope) => void
  }) => (
    <div data-testid="world-view-mock">
      scopes:{props.scopes.length};signals:{props.signals.length};selected:{props.selectedScopeId ?? 'none'}
      <button type="button" onClick={() => props.onSelect(props.scopes[0])}>Select globe scope</button>
    </div>
  ),
}))

function readyWithScopes(nodes: AtlasNode[], scopes: AtlasGeoScope[]): AtlasState {
  return {
    status: 'ready',
    projection: { generated_at: 'x', nodes, edges: [], scopes },
    retry: vi.fn(),
  }
}

const hormuzScope: AtlasGeoScope = {
  id: 'geo_scope:s1', room_id: 'room-h',
  lineage_root_id: 'geo_scope:s1',
  subject: { entity: 'rooms', id: 'room-h' },
  kind: 'polygon' as const,
  geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 26]]] },
  label: 'Strait of Hormuz (approx.)', authority: 'human_confirmed' as const,
  provenance: {
    provider: 'human', acquisition: 'human', source_id: 'scope-source-1',
    url: 'https://source.test/scope-1', credit: 'sketch',
  },
  source_state: 'ok' as const, revision_action: 'place', review_note: null, review_state: 'accepted',
  freshness: { state: 'current', observed_at: null, retrieved_at: '2026-08-25T00:00:00Z', expires_at: null },
  centroid: [56, 26.5] as [number, number],
  retrieved_at: '2026-08-25T00:00:00Z', created_at: '2026-08-25T00:00:00Z',
}

const vesselSignal: WorldSignal = {
  id: 'world_signal:ais:contact-1', provider: 'ais', source_id: 'contact-1',
  room_id: 'room-h', layer: 'vessels', kind: 'point',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  provenance: {
    provider: 'ais', acquisition: 'adapter:ais', source_id: 'contact-1',
    url: 'https://provider.test/contact-1', credit: 'AIS provider credit',
  },
  source_state: 'partial', freshness: 'current', coverage: 'receiver footprint',
  observed_at: '2026-08-25T17:58:00Z', retrieved_at: '2026-08-25T17:59:00Z',
  expires_at: '2026-08-25T18:10:00Z', label: 'Vessel contact 1',
  details: { speed_knots: 12.4 },
}

function readyWithWorld(
  nodes: AtlasNode[], scopes: AtlasGeoScope[], signals: WorldSignal[], retry = vi.fn(),
): AtlasState {
  return {
    status: 'ready', retry,
    projection: {
      generated_at: 'x', nodes, edges: [], scopes, signals,
      signal_sources: {
        status: 'configured',
        sources: [{
          provider: 'ais', configured_room_ids: ['room-h'],
          source_state: 'partial', freshness: 'current',
          coverage: 'receiver footprint', observed_at: '2026-08-25T17:58:00Z',
          retrieved_at: '2026-08-25T17:59:00Z', expires_at: '2026-08-25T18:10:00Z',
          signal_count: signals.length,
        }],
      },
    },
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

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
    expect(await screen.findByTestId('world-view-mock')).toHaveTextContent('scopes:1')
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

  it('renders signals separately on the globe and in the complete no-WebGL list', async () => {
    render(
      <AtlasScene
        state={readyWithWorld(rooms, [hormuzScope], [vesselSignal])}
        onNavigate={vi.fn()}
        view="world"
        onView={vi.fn()}
      />,
    )

    expect(await screen.findByTestId('world-view-mock')).toHaveTextContent('scopes:1;signals:1')
    expect(screen.getByRole('region', { name: 'On the map' })).toHaveTextContent('Strait of Hormuz')
    const signals = screen.getByRole('region', { name: 'Live signals' })
    expect(signals).toHaveTextContent('Vessel contact 1')
    expect(signals).toHaveTextContent('receiver footprint')
  })

  it('keeps signals visible with the lazy globe absent and gives them no Focus/review action', () => {
    const onNavigate = vi.fn()
    render(
      <AtlasScene
        state={readyWithWorld(rooms, [hormuzScope], [vesselSignal])}
        onNavigate={onNavigate}
        onView={vi.fn()}
      />,
    )

    expect(screen.queryByTestId('world-view-mock')).toBeNull()
    const signalRow = screen.getByText('Vessel contact 1').closest('li')
    expect(signalRow).not.toBeNull()
    expect(signalRow).not.toHaveTextContent(/confirm|reject|review|focus/i)
    expect(signalRow?.querySelector('.atlas-row-open')).toBeNull()
    fireEvent.click(screen.getByText('Vessel contact 1'))
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('shows placement only to an authorized human and refreshes signals plus durable scopes', async () => {
    const retry = vi.fn()
    const refreshGeo = vi.fn()
    const place = vi.spyOn(api, 'placeWorldSignal').mockResolvedValue({
      ...hormuzScope,
      id: 'geo_scope:placed-contact',
      subject: { entity: 'rooms', id: 'room-h', field: vesselSignal.id },
      label: vesselSignal.label,
      authority: 'source_reported',
      revision_action: 'place_signal',
    })
    const state = readyWithWorld(rooms, [hormuzScope], [vesselSignal], retry)
    const { rerender } = render(
      <AtlasScene
        state={state}
        onNavigate={vi.fn()}
        signalRoomTokens={new Map()}
        onGeoChanged={refreshGeo}
      />,
    )
    expect(screen.queryByRole('button', { name: /Place Vessel contact 1/i })).toBeNull()

    rerender(
      <AtlasScene
        state={state}
        onNavigate={vi.fn()}
        signalRoomTokens={new Map([['room-h', 'token-h']])}
        onGeoChanged={refreshGeo}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Place Vessel contact 1/i }))
    await waitFor(() => expect(place).toHaveBeenCalledWith('room-h', vesselSignal.id, 'token-h'))
    expect(retry).toHaveBeenCalledOnce()
    expect(refreshGeo).toHaveBeenCalledOnce()

    rerender(
      <AtlasScene
        state={readyWithWorld(rooms, [{
          ...hormuzScope,
          id: 'geo_scope:placed-contact',
          subject: { entity: 'rooms', id: 'room-h', field: vesselSignal.id },
          label: vesselSignal.label,
          authority: 'source_reported',
          revision_action: 'place_signal',
        }], [vesselSignal])}
        onNavigate={vi.fn()}
        signalRoomTokens={new Map([['room-h', 'token-h']])}
        onGeoChanged={refreshGeo}
      />,
    )
    expect(screen.getByRole('region', { name: 'On the map' })).toHaveTextContent('Vessel contact 1')
    // Placement copies the observation; it does not consume or mutate the
    // process-local provider snapshot. The refreshed projections may carry
    // both the still-current signal and its new durable scope.
    expect(screen.getByRole('region', { name: 'Live signals' })).toHaveTextContent('Vessel contact 1')
  })

  it('shows a real placement failure in the visible signal row', async () => {
    vi.spyOn(api, 'placeWorldSignal').mockRejectedValue(new Error('signal is expired'))
    render(
      <AtlasScene
        state={readyWithWorld(rooms, [], [vesselSignal])}
        onNavigate={vi.fn()}
        signalRoomTokens={new Map([['room-h', 'token-h']])}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Place Vessel contact 1/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('signal is expired')
  })

  it('keeps another-room signal visible but read-only under the current room token', () => {
    const place = vi.spyOn(api, 'placeWorldSignal')
    const otherRoomSignal: WorldSignal = {
      ...vesselSignal,
      id: 'world_signal:ais:contact-other',
      source_id: 'contact-other',
      room_id: 'room-other',
      label: 'Other room vessel',
      provenance: { ...vesselSignal.provenance, source_id: 'contact-other' },
    }
    const twoRooms = [
      ...rooms,
      node({ id: 'room:room-other', kind: 'room', room_id: 'room-other', title: 'Other room' }),
    ]
    render(
      <AtlasScene
        state={readyWithWorld(twoRooms, [], [vesselSignal, otherRoomSignal])}
        onNavigate={vi.fn()}
        signalRoomTokens={new Map([['room-h', 'token-h']])}
      />,
    )

    expect(screen.getByText('Other room vessel')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Place Other room vessel/i })).toBeNull()
    expect(screen.getByRole('button', { name: /Place Vessel contact 1/i })).toBeInTheDocument()
    fireEvent.click(screen.getByText('Other room vessel'))
    expect(place).not.toHaveBeenCalled()
  })

  it('renders explicit not-configured source state instead of treating empty as zero observations', () => {
    render(
      <AtlasScene
        state={{
          status: 'ready', retry: vi.fn(),
          projection: {
            generated_at: 'x', nodes: rooms, edges: [], scopes: [], signals: [],
            signal_sources: { status: 'not_configured', sources: [] },
          },
        }}
        onNavigate={vi.fn()}
      />,
    )
    expect(screen.getByRole('region', { name: 'Live signals' })).toHaveTextContent('not configured')
  })

  const causalBinding: CausalGeoBinding = {
    id: 'field_mark:causal',
    current_scope_id: hormuzScope.id,
    evidence_scope_id: 'geo_scope:root-s1',
    relation: 'supports',
    review_state: 'confirmed',
    provisional: false,
    target: {
      room_id: 'room-h', book_id: 'hormuz-book', node_id: 'shipping',
      node_label: 'Shipping chokepoint',
    },
  }

  function synapseState(): AtlasState {
    return {
      status: 'ready',
      retry: vi.fn(),
      projection: {
        generated_at: 'x', nodes: rooms, edges: [],
        scopes: [{ ...hormuzScope, lineage_root_id: 'geo_scope:root-s1' }],
        causal_bindings: [causalBinding],
        causal_bindings_total: 1,
        causal_bindings_omitted: 0,
        causal_bindings_complete: true,
      },
    }
  }

  it('selects the current live scope when Focus carries its lineage root', () => {
    render(
      <AtlasScene
        state={synapseState()}
        selectedObjectId="geo_scope:root-s1"
        onNavigate={vi.fn()}
      />,
    )

    const row = screen.getByRole('button', { name: /Strait of Hormuz/ })
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(row).toHaveTextContent('Selected')
  })

  it('keeps complete scope provenance visible in the list without WebGL', () => {
    render(<AtlasScene state={synapseState()} onNavigate={vi.fn()} />)

    const provenance = screen.getByRole('group', {
      name: 'Source provenance for Strait of Hormuz (approx.)',
    })
    expect(provenance).toHaveTextContent('Providerhuman')
    expect(provenance).toHaveTextContent('Acquisitionhuman')
    expect(provenance).toHaveTextContent('Source IDscope-source-1')
    expect(provenance).toHaveTextContent('Exact URLhttps://source.test/scope-1')
    expect(provenance).toHaveTextContent('Creditsketch')
  })

  it('keeps Field mark selection while highlighting and explaining its World evidence', async () => {
    const onNavigate = vi.fn()
    render(
      <AtlasScene
        state={synapseState()}
        selectedObjectId={causalBinding.id}
        onNavigate={onNavigate}
        view="world;room=room-h"
        onView={vi.fn()}
      />,
    )

    expect(await screen.findByTestId('world-view-mock')).toHaveTextContent(
      `selected:${hormuzScope.id}`,
    )
    const overlays = screen.getAllByRole('list', { name: /Causal bindings for Strait of Hormuz/ })
    expect(overlays.length).toBeGreaterThanOrEqual(2)
    expect(overlays[0]).toHaveTextContent('Supports')
    expect(overlays[0]).toHaveTextContent('Shipping chokepoint')
    expect(overlays[0]).toHaveTextContent('Confirmed')

    fireEvent.click(screen.getAllByRole('button', { name: 'Supports' })[0])
    expect(onNavigate).toHaveBeenCalledWith({
      roomId: 'room-h', object: causalBinding.id,
    })
  })

  it('states when the bounded projection omits causal bindings', () => {
    const state = synapseState()
    if (state.status !== 'ready') throw new Error('fixture must be ready')
    state.projection.causal_bindings_omitted = 3
    state.projection.causal_bindings_complete = false

    render(<AtlasScene state={state} onNavigate={vi.fn()} />)

    expect(screen.getByText('3 more causal bindings omitted.')).toBeInTheDocument()
  })
})
