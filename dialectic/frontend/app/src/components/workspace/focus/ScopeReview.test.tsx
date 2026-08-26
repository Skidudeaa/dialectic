import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CausalGeoBinding } from '../../../types/atlas.ts'
import type { GeoScopeReview } from '../../../types/geo.ts'
import { ScopeReview } from './ScopeReview.tsx'

const oldEvidence = {
  id: 'geo_scope:old-evidence', room_id: 'r1',
  subject: { entity: 'messages', id: 'msg-1', field: null },
  kind: 'polygon' as const,
  geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 27], [55, 26]]] },
  label: 'Strait of Hormuz', authority: 'source_reported' as const,
  provenance: {
    provider: 'natural_earth', acquisition: 'adapter', source_id: 'ne-1',
    url: null, credit: 'Made with Natural Earth',
  },
  source_state: 'ok' as const, revision_action: 'place' as const, review_note: null,
  review_state: 'accepted' as const,
  freshness: { state: 'current' as const, retrieved_at: '2026-08-25T00:00:00Z' },
  centroid: [56, 26.5] as [number, number], retrieved_at: '2026-08-25T00:00:00Z',
  supersedes_id: null, created_by: 'amo', created_at: '2026-08-25T00:00:00Z',
}

const review: GeoScopeReview = {
  root_id: oldEvidence.id,
  current: {
    ...oldEvidence,
    id: 'geo_scope:current',
    revision_action: 'redraw',
    supersedes_id: 'old-evidence',
  },
  lineage: [oldEvidence],
  subject_destination: { room_id: 'r1', thread_id: 'thread-1', message_id: 'msg-1' },
}

const binding: CausalGeoBinding = {
  id: 'field_mark:causal',
  current_scope_id: 'geo_scope:current',
  evidence_scope_id: 'geo_scope:old-evidence',
  relation: 'supports',
  review_state: 'confirmed',
  provisional: false,
  target: {
    room_id: 'r1', book_id: 'hormuz', node_id: 'shipping', node_label: 'Shipping chokepoint',
  },
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ScopeReview causal evidence', () => {
  it('renders the shared semantics and selects the exact Field mark without changing axes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(review)))
    const onNavigate = vi.fn()
    render(
      <ScopeReview
        roomId="r1"
        scopeId="geo_scope:old-evidence"
        canAct={false}
        onClose={vi.fn()}
        onNavigate={onNavigate}
        onChanged={vi.fn()}
        onMarked={vi.fn()}
        worldBindings={[
          binding,
          {
            ...binding,
            id: 'field_mark:foreign',
            target: { ...binding.target, room_id: 'r2', node_label: 'Foreign thesis' },
          },
        ]}
      />,
    )

    const causalList = await screen.findByRole('list', { name: 'Causal bindings for Strait of Hormuz' })
    expect(within(causalList).getByText('Strait of Hormuz')).toBeInTheDocument()
    expect(within(causalList).getByRole('button', { name: 'Supports' })).toBeInTheDocument()
    expect(within(causalList).getByText('Shipping chokepoint')).toBeInTheDocument()
    expect(within(causalList).getByText('Confirmed')).toBeInTheDocument()
    expect(screen.queryByText('Foreign thesis')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Supports' }))
    expect(onNavigate).toHaveBeenCalledWith({ object: 'field_mark:causal' })
  })
})
