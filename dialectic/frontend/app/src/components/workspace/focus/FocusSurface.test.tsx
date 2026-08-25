import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FocusSurface } from './FocusSurface'
import type { FieldMark, WorkspaceObject } from '../../../types/workspace.ts'
import type { FieldMarksState } from '../../../hooks/useFieldMarks.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import { useAppStore } from '../../../stores/appStore.ts'

const mark = (overrides: Partial<FieldMark> & { id: string; relation: FieldMark['relation'] }): FieldMark => ({
  room_id: 'r1', thread_id: null, origin: 'inferred', review: 'provisional',
  deliberative_status: 'active', subjects: [], title: '', payload: {},
  supersedes_id: null, caused_by_id: null, actor_user_id: null,
  provenance: 'field_inference', created_at: '2026-08-13T10:00:00Z', reviews: [],
  ...overrides,
})

const object = (overrides: Partial<WorkspaceObject> & { id: string; kind: WorkspaceObject['kind'] }): WorkspaceObject => ({
  room_id: 'r1', branch_id: null, title: 'A reading', summary: '', status: 'active',
  created_at: 'x', updated_at: 'x',
  provenance: { origin: 'human', actor_user_id: null, detail: null },
  relationships: [], available_actions: [], review_state: 'none',
  source_entity: [], source_event: null,
  ...overrides,
})

const noObjects: WorkspaceObjectsState = { status: 'ready', objects: [], generatedAt: 'x', retry: () => {} }
const noMarks: FieldMarksState = { status: 'ready', marks: [], generatedAt: 'x', refresh: () => {} }
const baseProps = {
  canAct: true,
  onNavigate: vi.fn(),
  onReview: vi.fn().mockResolvedValue(undefined),
}

function geoScope(overrides: Record<string, unknown> = {}) {
  return {
    id: 'geo_scope:root-1', room_id: 'r1',
    subject: { entity: 'messages', id: 'msg-1', field: null },
    kind: 'polygon',
    geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 27], [55, 26]]] },
    label: 'Strait of Hormuz', authority: 'source_reported',
    provenance: { provider: 'natural_earth', acquisition: 'adapter', source_id: 'ne-1', url: null, credit: 'Made with Natural Earth' },
    source_state: 'ok', revision_action: 'place_signal', review_note: null,
    review_state: 'accepted', freshness: {
      state: 'current', observed_at: '2026-08-24T12:00:00Z',
      retrieved_at: '2026-08-25T00:00:00Z', expires_at: null,
    },
    centroid: [56, 26.5], observed_at: '2026-08-24T12:00:00Z',
    retrieved_at: '2026-08-25T00:00:00Z', expires_at: null,
    confirmed_by: null, confirmed_at: null, supersedes_id: null,
    created_by: 'provider-agent', created_at: '2026-08-25T00:00:00Z',
    ...overrides,
  }
}

function geoReview(overrides: Record<string, unknown> = {}) {
  const current = geoScope()
  return {
    root_id: 'geo_scope:root-1', current, lineage: [current],
    subject_destination: { room_id: 'r1', thread_id: 'thread-1', message_id: 'msg-1' },
    ...overrides,
  }
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useAppStore.setState({ accessToken: null })
})

describe('FocusSurface', () => {
  it('shows loading while its projections are still in flight', () => {
    render(
      <FocusSurface
        {...baseProps}
        objectId="field_mark:1"
        objects={{ status: 'loading' }}
        fieldMarks={{ status: 'loading' }}
      />,
    )
    expect(screen.getByTestId('scene-loading')).toBeInTheDocument()
  })

  it('renders its own unavailable state for an id that resolves to nothing — never a 404', () => {
    render(
      <FocusSurface {...baseProps} objectId="field_mark:missing" objects={noObjects} fieldMarks={noMarks} />,
    )
    expect(screen.getByTestId('scene-empty')).toBeInTheDocument()
  })

  it('shows the three epistemic axes as text labels for a field mark — never color-only (§17.4)', () => {
    const theMark = mark({
      id: 'field_mark:1', relation: 'emerging_position', title: 'Rates will fall',
      origin: 'inferred', review: 'contested', deliberative_status: 'active',
    })
    render(
      <FocusSurface
        {...baseProps}
        objectId="field_mark:1"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [theMark], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    expect(screen.getByText('Rates will fall')).toBeInTheDocument()
    expect(screen.getByText('Inferred')).toBeInTheDocument()
    expect(screen.getByText('contested')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('shows the axes for a non-field-mark object too', () => {
    const reading = object({
      id: 'reading:1', kind: 'reading', title: 'The tariff piece', status: 'active', review_state: 'accepted',
    })
    render(
      <FocusSurface
        {...baseProps}
        objectId="reading:1"
        objects={{ status: 'ready', objects: [reading], generatedAt: 'x', retry: () => {} }}
        fieldMarks={noMarks}
      />,
    )
    expect(screen.getByText('The tariff piece')).toBeInTheDocument()
    expect(screen.getByText('Accepted')).toBeInTheDocument()
  })

  it('clears the object axis via onNavigate from the Back/Close control', () => {
    const onNavigate = vi.fn()
    const theMark = mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'X' })
    render(
      <FocusSurface
        {...baseProps}
        onNavigate={onNavigate}
        objectId="field_mark:1"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [theMark], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Close Focus' }))
    expect(onNavigate).toHaveBeenCalledWith({ object: null })
  })

  it('does not render FocusActions when canAct is false (guest boundary)', () => {
    const theMark = mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'X' })
    render(
      <FocusSurface
        {...baseProps}
        canAct={false}
        objectId="field_mark:1"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [theMark], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    expect(screen.queryByRole('button', { name: 'Confirm' })).toBeNull()
  })

  it('shows one-tap review actions gated on membership, disabled once already in that state', () => {
    const theMark = mark({
      id: 'field_mark:1', relation: 'emerging_position', title: 'X', review: 'confirmed',
    })
    render(
      <FocusSurface
        {...baseProps}
        objectId="field_mark:1"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [theMark], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Contest' })).not.toBeDisabled()
  })

  it('shows incoming relationships from other marks that name this one as a subject', () => {
    const claim = mark({ id: 'field_mark:claim', relation: 'claim_group', title: 'Rates fall' })
    const support = mark({
      id: 'field_mark:sup', relation: 'supports', title: '',
      subjects: [{ entity: 'field_marks', id: 'claim', field: null }],
    })
    render(
      <FocusSurface
        {...baseProps}
        objectId="field_mark:claim"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [claim, support], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    expect(screen.getByText('Supports')).toBeInTheDocument()
  })

  it('shows adjudicated causal roles and navigates to the matching Builder room', () => {
    act(() => useAppStore.setState({ accessToken: 'session-token' }))
    const causal = mark({
      id: 'field_mark:causal', relation: 'supports', title: 'Hormuz supports shipping',
      review: 'confirmed',
      subjects: [
        { entity: 'rooms', id: 'r1', field: 'thesis_node:hormuz:shipping' },
        { entity: 'geo_scopes', id: 'scope-1', field: null },
      ],
      payload: { node_label: 'Shipping chokepoint', scope_label: 'Strait of Hormuz' },
    })
    render(
      <FocusSurface
        {...baseProps}
        objectId="field_mark:causal"
        objects={noObjects}
        fieldMarks={{ status: 'ready', marks: [causal], generatedAt: 'x', refresh: () => {} }}
      />,
    )
    expect(screen.getByText('Strait of Hormuz')).toBeInTheDocument()
    expect(screen.getByText('Supports')).toBeInTheDocument()
    expect(screen.getByText(/Shipping chokepoint/)).toBeInTheDocument()
    expect(screen.getAllByText('confirmed').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Open node in Builder' })).toHaveAttribute(
      'href',
      'https://td.somacura.org/builder#dialectic_token=session-token&dialectic_room=r1',
    )
  })

  it('loads a geo scope independently of object projections and shows every lineage fact and evidence axis', async () => {
    const placed = geoScope({
      revision_action: 'place', authority: 'human_confirmed', created_by: 'amo',
      confirmed_by: 'amo', created_at: '2026-08-23T10:00:00Z',
    })
    const redrawn = geoScope({
      id: 'geo_scope:revision-2', supersedes_id: 'root-1', revision_action: 'redraw',
      review_note: 'shoreline corrected', created_by: 'bea', confirmed_by: 'bea',
      created_at: '2026-08-24T11:00:00Z',
    })
    const legacyRejected = geoScope({
      id: 'geo_scope:revision-3', supersedes_id: 'revision-2',
      source_state: 'confirmed_empty', revision_action: 'reject', review_state: 'rejected',
      review_note: 'wrong basin', created_by: 'amo', confirmed_by: 'amo',
      created_at: '2026-08-25T12:00:00Z',
    })
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(geoReview({
      current: legacyRejected, lineage: [placed, redrawn, legacyRejected],
    })))
    vi.stubGlobal('fetch', fetchMock)

    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={{ status: 'loading' }}
        fieldMarks={{ status: 'loading' }}
      />,
    )

    expect(await screen.findByRole('heading', { name: 'Strait of Hormuz' })).toBeInTheDocument()
    expect(screen.getByText('Authority')).toBeInTheDocument()
    expect(screen.getByText('Source condition')).toBeInTheDocument()
    expect(screen.getByText('Freshness')).toBeInTheDocument()
    expect(screen.getByText('Review decision')).toBeInTheDocument()
    expect(screen.getAllByText('Rejected').length).toBeGreaterThan(0)
    const history = screen.getByRole('list', { name: 'Scope history' })
    expect(within(history).getAllByRole('listitem')).toHaveLength(3)
    expect(history).toHaveTextContent('2026-08-23')
    expect(history).toHaveTextContent('amo')
    expect(history).toHaveTextContent('Place')
    expect(history).toHaveTextContent('Redraw')
    expect(history).toHaveTextContent('shoreline corrected')
    expect(history).toHaveTextContent('natural_earth · adapter')
    expect(history).toHaveTextContent('Polygon · 5 vertices')
    expect(history).toHaveTextContent('wrong basin')
    expect(fetchMock).toHaveBeenCalledWith('/rooms/r1/geo/root-1/review', expect.any(Object))
  })

  it('opens the stored message subject with the exact server-derived thread and message destination', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(geoReview())))
    const onNavigate = vi.fn()
    render(
      <FocusSurface
        {...baseProps}
        onNavigate={onNavigate}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Open subject' }))
    expect(onNavigate).toHaveBeenCalledWith({
      threadId: 'thread-1', messageId: 'msg-1', object: null,
    })
  })

  it('canonicalizes a selected successor to the review root through replace navigation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(geoReview())))
    const onNavigate = vi.fn()
    render(
      <FocusSurface
        {...baseProps}
        onNavigate={onNavigate}
        objectId="geo_scope:revision-2"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )

    await screen.findByRole('heading', { name: 'Strait of Hormuz' })
    expect(onNavigate).toHaveBeenCalledWith({ object: 'geo_scope:root-1', historyMode: 'replace' })
  })

  it('offers proposal decisions, keeps the root selected, and refreshes review plus projections after a write', async () => {
    const proposal = geoScope({ authority: 'machine_proposed', revision_action: 'propose', review_state: 'proposed' })
    const confirmed = geoScope({ id: 'geo_scope:confirmed', supersedes_id: 'root-1', authority: 'human_confirmed', revision_action: 'confirm' })
    const before = geoReview({ current: proposal, lineage: [proposal] })
    const after = geoReview({ current: confirmed, lineage: [proposal, confirmed] })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(before))
      .mockResolvedValueOnce(jsonResponse(confirmed))
      .mockResolvedValueOnce(jsonResponse(after))
    vi.stubGlobal('fetch', fetchMock)
    const onNavigate = vi.fn()
    const onGeoChanged = vi.fn()
    render(
      <FocusSurface
        {...baseProps}
        onNavigate={onNavigate}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
        onGeoChanged={onGeoChanged}
      />,
    )

    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Review note'), { target: { value: 'matches the source' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(onGeoChanged).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('list', { name: 'Scope history' })).toHaveTextContent('Confirm'))

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/rooms/r1/geo/root-1/review',
      '/rooms/r1/geo/root-1/confirm',
      '/rooms/r1/geo/root-1/review',
    ])
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({ note: 'matches the source' })
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('offers ratify, redraw, and supersede for an accepted unratified placement and redraws without a client supersedes id', async () => {
    const accepted = geoScope({ revision_action: 'place', authority: 'human_confirmed', review_state: 'accepted' })
    const redrawn = geoScope({ id: 'geo_scope:redrawn', supersedes_id: 'root-1', revision_action: 'redraw' })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: accepted, lineage: [accepted] })))
      .mockResolvedValueOnce(jsonResponse(redrawn))
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: redrawn, lineage: [accepted, redrawn] })))
    vi.stubGlobal('fetch', fetchMock)
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
        onGeoChanged={vi.fn()}
      />,
    )

    expect(await screen.findByRole('button', { name: 'Ratify' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Supersede' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Redraw' }))
    fireEvent.change(screen.getByLabelText('Placement label'), { target: { value: 'Corrected Strait' } })
    fireEvent.change(screen.getByLabelText('Review note'), { target: { value: 'shoreline corrected' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save redraw' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))

    const body = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)
    expect(fetchMock.mock.calls[1][0]).toBe('/rooms/r1/geo/root-1/redraw')
    expect(body).toEqual({
      label: 'Corrected Strait', geometry: accepted.geometry, note: 'shoreline corrected',
    })
    expect(body).not.toHaveProperty('supersedes_id')
  })

  it('does not offer ratify again after the current revision is a ratification', async () => {
    const ratified = geoScope({ revision_action: 'ratify', authority: 'human_confirmed', review_state: 'accepted' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(geoReview({ current: ratified, lineage: [ratified] }))))
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    await screen.findByRole('heading', { name: 'Strait of Hormuz' })
    expect(screen.queryByRole('button', { name: 'Ratify' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Redraw' })).toBeInTheDocument()
  })

  it('does not offer ratify when the accepted current revision already records a human review act', async () => {
    const confirmed = geoScope({ revision_action: 'confirm', authority: 'human_confirmed', review_state: 'accepted' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(geoReview({ current: confirmed, lineage: [confirmed] }))))
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    await screen.findByRole('heading', { name: 'Strait of Hormuz' })
    expect(screen.queryByRole('button', { name: 'Ratify' })).toBeNull()
  })

  it('executes ratify and supersede through the current live revision', async () => {
    const accepted = geoScope({ revision_action: 'place', review_state: 'accepted' })
    const ratified = geoScope({ id: 'geo_scope:ratified', supersedes_id: 'root-1', revision_action: 'ratify' })
    const ratifyFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: accepted, lineage: [accepted] })))
      .mockResolvedValueOnce(jsonResponse(ratified))
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: ratified, lineage: [accepted, ratified] })))
    vi.stubGlobal('fetch', ratifyFetch)
    const first = render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Ratify' }))
    await waitFor(() => expect(ratifyFetch).toHaveBeenCalledTimes(3))
    expect(ratifyFetch.mock.calls[1][0]).toBe('/rooms/r1/geo/root-1/ratify')
    first.unmount()

    const reviewed = geoScope({ revision_action: 'redraw', review_state: 'accepted' })
    const superseded = geoScope({ id: 'geo_scope:retired', supersedes_id: 'root-1', revision_action: 'supersede', review_state: 'rejected' })
    const supersedeFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: reviewed, lineage: [reviewed] })))
      .mockResolvedValueOnce(jsonResponse(superseded))
      .mockResolvedValueOnce(jsonResponse(geoReview({ current: superseded, lineage: [reviewed, superseded] })))
    vi.stubGlobal('fetch', supersedeFetch)
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Supersede' }))
    await waitFor(() => expect(supersedeFetch).toHaveBeenCalledTimes(3))
    expect(supersedeFetch.mock.calls[1][0]).toBe('/rooms/r1/geo/root-1/supersede')
  })

  it('keeps scope review and complete history readable for guests without exposing writes', async () => {
    const accepted = geoScope({ revision_action: 'place', review_state: 'accepted' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(geoReview({ current: accepted, lineage: [accepted] }))))
    render(
      <FocusSurface
        {...baseProps}
        canAct={false}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    expect(await screen.findByRole('list', { name: 'Scope history' })).toHaveTextContent('Place')
    expect(screen.queryByRole('button', { name: 'Ratify' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Redraw' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Supersede' })).toBeNull()
  })

  it('selects a thesis node and files supports/challenges/context into normal Field review', async () => {
    const structure = {
      id: 'hormuz', meta: { title: 'Hormuz' },
      nodes: [
        { id: 'shipping', label: 'Shipping chokepoint', type: 'event', phase: 1, state: 'watching', x: 0, y: 0 },
        { id: 'freight', label: 'Freight rates', type: 'market', phase: 2, state: 'watching', x: 1, y: 1 },
      ],
      edges: [], scenarios: [],
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(geoReview()))
      .mockResolvedValueOnce(jsonResponse(structure))
      .mockResolvedValueOnce(jsonResponse({ id: 'field_mark:new' }))
    vi.stubGlobal('fetch', fetchMock)
    const onMarked = vi.fn()
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
        onMarked={onMarked}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Bind to thesis node' }))
    await screen.findByLabelText('Thesis node')
    fireEvent.change(screen.getByLabelText('Causal relation'), { target: { value: 'context' } })
    fireEvent.change(screen.getByLabelText('Thesis node'), { target: { value: 'freight' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to Field' }))

    await waitFor(() => expect(onMarked).toHaveBeenCalledTimes(1))
    expect(fetchMock.mock.calls[1][0]).toBe('/rooms/r1/trading/structure')
    expect(fetchMock.mock.calls[2][0]).toBe('/rooms/r1/field/marks')
    expect(JSON.parse((fetchMock.mock.calls[2][1] as RequestInit).body as string)).toEqual({
      relation: 'context',
      subjects: [
        { entity: 'geo_scopes', id: 'root-1' },
        { entity: 'rooms', id: 'r1', field: 'thesis_node:hormuz:freight' },
      ],
      title: 'Strait of Hormuz context Freight rates',
      payload: { node_label: 'Freight rates' },
    })
  })

  it('keeps causal binding unavailable when the authenticated structure cannot load', async () => {
    const failed = { ok: false, status: 503, json: vi.fn().mockResolvedValue({ detail: 'desk unavailable' }) } as unknown as Response
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(geoReview()))
      .mockResolvedValueOnce(failed)
    vi.stubGlobal('fetch', fetchMock)
    render(
      <FocusSurface
        {...baseProps}
        objectId="geo_scope:root-1"
        roomId="r1"
        objects={noObjects}
        fieldMarks={noMarks}
      />,
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Bind to thesis node' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/desk unavailable/i)
    expect(screen.queryByRole('button', { name: 'Add to Field' })).toBeNull()
  })
})
