import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CausalGeoBinding } from '../../../types/atlas.ts'
import { CausalBindingList } from './CausalBindingList.tsx'

const confirmed: CausalGeoBinding = {
  id: 'field_mark:causal',
  current_scope_id: 'geo_scope:current',
  evidence_scope_id: 'geo_scope:root',
  relation: 'supports',
  review_state: 'confirmed',
  provisional: false,
  target: {
    room_id: 'room-h',
    book_id: 'hormuz-book',
    node_id: 'shipping',
    node_label: 'Shipping chokepoint',
  },
}

describe('CausalBindingList', () => {
  it('renders exact causal semantics and opens the existing Field mark', () => {
    const onOpenMark = vi.fn()
    render(
      <CausalBindingList
        scopeLabel="Strait of Hormuz"
        bindings={[confirmed]}
        onOpenMark={onOpenMark}
      />,
    )

    expect(screen.getByText('Strait of Hormuz')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Supports' })).toBeInTheDocument()
    expect(screen.getByText('Shipping chokepoint')).toBeInTheDocument()
    expect(screen.getByText('Confirmed')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Supports' }))
    expect(onOpenMark).toHaveBeenCalledWith(confirmed)
  })

  it('states provisional review in words rather than color alone', () => {
    render(
      <CausalBindingList
        scopeLabel="Strait of Hormuz"
        bindings={[{ ...confirmed, review_state: 'provisional', provisional: true }]}
        onOpenMark={vi.fn()}
      />,
    )

    expect(screen.getByText('Provisional')).toBeInTheDocument()
  })
})
