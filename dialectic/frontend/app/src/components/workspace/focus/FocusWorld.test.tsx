import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FocusWorld } from './FocusWorld'
import { api } from '../../../lib/api.ts'
import type { WorkspaceObject } from '../../../types/workspace.ts'
import type { GeoScope } from '../../../types/geo.ts'
import type { GeoScopesState } from '../../../hooks/useGeoScopes.ts'

const reading: WorkspaceObject = {
  id: 'reading:r1', kind: 'reading', room_id: 'room-h', branch_id: null,
  title: 'Tankers slow', summary: '', status: 'wire',
  created_at: '2026-08-25T00:00:00Z', updated_at: '2026-08-25T00:00:00Z',
  provenance: { origin: 'dialectic', actor_user_id: null, detail: null }, relationships: [], available_actions: [],
  review_state: 'none', source_entity: [{ entity: 'reading_items', id: 'r1', field: null }], source_event: null,
}

function scope(partial: Partial<GeoScope>): GeoScope {
  return {
    id: 'geo_scope:s', room_id: 'room-h', subject: { entity: 'rooms', id: 'room-h' },
    kind: 'polygon', geometry: { type: 'Polygon', coordinates: [[[55, 26], [57, 26], [57, 27], [55, 26]]] },
    label: 'Strait', authority: 'human_confirmed',
    provenance: { provider: 'human', acquisition: 'human', credit: 'sketch' },
    source_state: 'ok', centroid: [56, 26.5],
    retrieved_at: '2026-08-25T00:00:00Z', created_at: '2026-08-25T00:00:00Z',
    ...partial,
  }
}

function ready(scopes: GeoScope[]): GeoScopesState {
  return { status: 'ready', projection: { generated_at: 'x', room_id: 'room-h', scopes }, retry: vi.fn() }
}

const roomArea = scope({ id: 'geo_scope:area', label: 'Strait of Hormuz (approx.)' })
const placedHere = scope({ id: 'geo_scope:p1', subject: { entity: 'reading_items', id: 'r1' }, kind: 'region', label: 'Persian Gulf' })
const proposedHere = scope({
  id: 'geo_scope:p2', subject: { entity: 'reading_items', id: 'r1' }, kind: 'region', label: 'Gulf of Oman',
  authority: 'machine_proposed', provenance: { provider: 'natural_earth', acquisition: 'llm', credit: 'Made with Natural Earth' },
})

describe('FocusWorld', () => {
  it('says plainly when the object is not placed, and offers the room areas', () => {
    render(<FocusWorld roomId="room-h" object={reading} geo={ready([roomArea])} canAct onChanged={vi.fn()} onMarked={vi.fn()} />)
    expect(screen.getByText('Not placed on the world.')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Strait of Hormuz (approx.)' })).toBeInTheDocument()
  })

  it('places through the geo door, copying the chosen area', async () => {
    const create = vi.spyOn(api, 'createGeoScope').mockResolvedValue(placedHere)
    const onChanged = vi.fn()
    render(<FocusWorld roomId="room-h" object={reading} geo={ready([roomArea])} canAct onChanged={onChanged} onMarked={vi.fn()} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'geo_scope:area' } })
    fireEvent.click(screen.getByRole('button', { name: 'Place' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(create).toHaveBeenCalledWith('room-h', expect.objectContaining({
      subject: { entity: 'reading_items', id: 'r1' },
      kind: 'region',
      geometry: roomArea.geometry,
      label: 'Strait of Hormuz (approx.)',
      provenance: expect.objectContaining({ provider: 'room_scope', source_id: 'area', credit: 'sketch' }),
    }))
  })

  it('a proposal offers Confirm / Reject and nothing else; a confirmed scope offers Mark', async () => {
    const confirm = vi.spyOn(api, 'confirmGeoScope').mockResolvedValue(placedHere)
    const mark = vi.spyOn(api, 'createFieldMark').mockResolvedValue({} as never)
    const onChanged = vi.fn()
    const onMarked = vi.fn()
    render(<FocusWorld roomId="room-h" object={reading} geo={ready([roomArea, placedHere, proposedHere])} canAct onChanged={onChanged} onMarked={onMarked} />)
    const rows = screen.getAllByRole('listitem')
    const proposed = rows.find((r) => r.getAttribute('data-authority') === 'machine_proposed')!
    const confirmed = rows.find((r) => r.getAttribute('data-authority') === 'human_confirmed')!
    expect(proposed).toHaveTextContent('proposed')
    expect(proposed.querySelector('button[type="button"]')?.textContent).toBe('Confirm')
    expect(Array.from(proposed.querySelectorAll('button')).map((b) => b.textContent)).toEqual(['Confirm', 'Reject'])
    expect(Array.from(confirmed.querySelectorAll('button')).map((b) => b.textContent)).toEqual(['Mark as evidence here'])

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(confirm).toHaveBeenCalledWith('room-h', 'p2')

    fireEvent.click(screen.getByRole('button', { name: 'Mark as evidence here' }))
    await waitFor(() => expect(onMarked).toHaveBeenCalled())
    expect(mark).toHaveBeenCalledWith('room-h', expect.objectContaining({
      relation: 'evidence_attachment',
      subjects: [{ entity: 'geo_scopes', id: 'p1' }, { entity: 'reading_items', id: 'r1' }],
    }))
  })

  it('offers no writes to a viewer who cannot act', () => {
    render(<FocusWorld roomId="room-h" object={reading} geo={ready([roomArea, proposedHere])} canAct={false} onChanged={vi.fn()} onMarked={vi.fn()} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText('Gulf of Oman')).toBeInTheDocument()
  })
})
