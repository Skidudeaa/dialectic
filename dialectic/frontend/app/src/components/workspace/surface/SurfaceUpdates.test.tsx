import type { ComponentProps } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SurfaceUpdates } from './SurfaceUpdates'
import { api } from '../../../lib/api'
import type { ReadingLibraryItem } from '../../../types'
import type { WorldObservation } from '../../../types/geo'
import type { FieldMark } from '../../../types/workspace'

vi.mock('../../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../../lib/api')>('../../../lib/api')
  return { ...actual, api: { ...actual.api, getReadingLibrary: vi.fn() } }
})

afterEach(() => vi.clearAllMocks())

const provenance = { provider: 'nasa_firms', acquisition: 'VIIRS', credit: 'NASA FIRMS' }

function fireObs(over: Partial<WorldObservation> & { id: string }): WorldObservation {
  return {
    scope_id: 'scope-1',
    scope_label: 'Persian Gulf',
    provider: 'firms',
    signal_id: `sig-${over.id}`,
    layer: 'fires',
    kind: 'point',
    label: `Fire cell ${over.id}`,
    geometry: { type: 'Point', coordinates: [0, 0] },
    provenance,
    details: { frp: 10, confidence: 'nominal', satellite: 'VIIRS-SNPP', novel: false },
    retrieved_at: '2026-09-02T12:00:00Z',
    first_seen_at: '2026-09-02T10:00:00Z',
    last_seen_at: '2026-09-02T10:00:00Z',
    seen_count: 1,
    ...over,
  }
}

function readingItem(over: Partial<ReadingLibraryItem> & { id: string }): ReadingLibraryItem {
  return {
    url: `https://example.com/${over.id}`,
    title: `Reading ${over.id}`,
    author: null,
    site: 'example.com',
    published: null,
    summary: 'summary',
    source: 'wire',
    saved_by_user_id: null,
    created_at: '2026-09-02T09:00:00Z',
    current_captured_at: null,
    content_sha256: null,
    current_revision_id: null,
    revision_count: 1,
    capture_mode: null,
    ...over,
  }
}

function fieldMark(over: Partial<FieldMark> & { id: string }): FieldMark {
  return {
    room_id: 'r1',
    thread_id: null,
    relation: 'supports',
    origin: 'inferred',
    review: 'provisional',
    deliberative_status: 'active',
    subjects: [],
    title: `Mark ${over.id}`,
    payload: {},
    supersedes_id: null,
    caused_by_id: null,
    actor_user_id: null,
    provenance: 'field_inference',
    created_at: '2026-09-02T09:00:00Z',
    reviews: [],
    ...over,
  }
}

function renderSurface(partial: Partial<ComponentProps<typeof SurfaceUpdates>> = {}) {
  const props: ComponentProps<typeof SurfaceUpdates> = {
    roomId: 'r1',
    since: null,
    observations: [],
    marks: [],
    selectedId: null,
    onSelect: vi.fn(),
    onOpen: vi.fn(),
    onAttach: vi.fn(),
    attachTargetLabel: null,
    ...partial,
  }
  return { props, ...render(<SurfaceUpdates {...props} />) }
}

describe('SurfaceUpdates', () => {
  it('counts fires (novel only), readings and marks after the since filter, excluding an older fire', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({
      items: [readingItem({ id: 'read-1', created_at: '2026-09-02T13:00:00Z' })],
      next_before: null,
    })
    const since = '2026-09-02T12:00:00Z'
    renderSurface({
      since,
      observations: [
        fireObs({ id: 'old', first_seen_at: '2026-09-01T00:00:00Z', details: { frp: 20, novel: true } }),
        fireObs({ id: 'new', first_seen_at: '2026-09-02T13:00:00Z', details: { frp: 20, novel: true } }),
      ],
      marks: [fieldMark({ id: 'm1', created_at: '2026-09-02T13:00:00Z' })],
    })
    await waitFor(() => {
      expect(screen.getByText('Updates since you left · 1 new fire · 1 reading · 1 mark')).toBeInTheDocument()
    })
    // the excluded fire never renders a card
    expect(screen.queryByText('Fire cell old')).toBeNull()
  })

  it('reads "Latest updates" and counts everything when since is null', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    renderSurface({
      observations: [fireObs({ id: 'a', details: { frp: 1, novel: true } })],
    })
    await waitFor(() => {
      expect(screen.getByText('Latest updates · 1 new fire · 0 readings · 0 marks')).toBeInTheDocument()
    })
  })

  it('sorts novel fires before recurring, and novel fires by FRP descending', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    const { container } = renderSurface({
      observations: [
        fireObs({
          id: 'recurring', first_seen_at: '2026-09-02T15:00:00Z',
          details: { frp: 5, novel: false, baseline_days: 4 },
        }),
        fireObs({ id: 'novel-low', first_seen_at: '2026-09-02T09:00:00Z', details: { frp: 10, novel: true } }),
        fireObs({ id: 'novel-high', first_seen_at: '2026-09-02T08:00:00Z', details: { frp: 50, novel: true } }),
      ],
    })
    await waitFor(() => expect(api.getReadingLibrary).toHaveBeenCalled())
    const cards = container.querySelectorAll('.surf-upd-card')
    expect(cards).toHaveLength(3)
    expect(cards[0].textContent).toContain('Fire cell novel-high')
    expect(cards[1].textContent).toContain('Fire cell novel-low')
    expect(cards[2].textContent).toContain('Fire cell recurring')
  })

  it('sets the JSON MessageRef on the drag data transfer', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    const { container } = renderSurface({
      observations: [fireObs({ id: 'a', details: { frp: 5, novel: true } })],
    })
    await waitFor(() => expect(api.getReadingLibrary).toHaveBeenCalled())
    const card = container.querySelector('.surf-upd-card')!
    const setData = vi.fn()
    const dataTransfer = { setData, effectAllowed: '' }
    fireEvent.dragStart(card, { dataTransfer })
    expect(setData).toHaveBeenCalledWith('text/plain', expect.any(String))
    const call = setData.mock.calls.find(([key]) => key === 'application/x-dialectic-ref')
    expect(call).toBeDefined()
    const parsed = JSON.parse(call![1] as string)
    expect(parsed).toEqual({ entity: 'world_observations', id: 'a', label: 'Fire cell a · Persian Gulf' })
  })

  it('selects a card on tap and deselects it on a second tap', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    const onSelect = vi.fn()
    const { container, rerender, props } = renderSurface({
      observations: [fireObs({ id: 'a', details: { frp: 5, novel: true } })],
      onSelect,
    })
    await waitFor(() => expect(api.getReadingLibrary).toHaveBeenCalled())
    fireEvent.click(container.querySelector('.surf-upd-card')!)
    expect(onSelect).toHaveBeenCalledWith({ entity: 'world_observations', id: 'a', label: 'Fire cell a · Persian Gulf' })

    rerender(<SurfaceUpdates {...props} selectedId="a" onSelect={onSelect} />)
    fireEvent.click(container.querySelector('.surf-upd-card')!)
    expect(onSelect).toHaveBeenLastCalledWith(null)
  })

  it('offers Attach only once a node is focused, and calls onAttach without selecting the card', async () => {
    vi.mocked(api.getReadingLibrary).mockResolvedValue({ items: [], next_before: null })
    const onAttach = vi.fn()
    const onSelect = vi.fn()
    const { rerender, props } = renderSurface({
      observations: [fireObs({ id: 'a', details: { frp: 5, novel: true } })],
      onAttach,
      onSelect,
    })
    await waitFor(() => expect(api.getReadingLibrary).toHaveBeenCalled())
    expect(screen.queryByText(/Attach ▸/)).toBeNull()

    rerender(<SurfaceUpdates {...props} attachTargetLabel="Cascade phase 2" onAttach={onAttach} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Attach ▸ Cascade phase 2'))
    expect(onAttach).toHaveBeenCalledWith({ entity: 'world_observations', id: 'a', label: 'Fire cell a · Persian Gulf' })
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('shows a quiet readings-unavailable chip while fire cards still render', async () => {
    vi.mocked(api.getReadingLibrary).mockRejectedValue(new Error('network down'))
    renderSurface({
      observations: [fireObs({ id: 'a', details: { frp: 5, novel: true } })],
    })
    await waitFor(() => {
      expect(screen.getByText('readings unavailable: network down')).toBeInTheDocument()
    })
    expect(screen.getByText('Fire cell a')).toBeInTheDocument()
  })
})
