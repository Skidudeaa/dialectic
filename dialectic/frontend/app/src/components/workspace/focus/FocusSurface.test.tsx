import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FocusSurface } from './FocusSurface'
import type { FieldMark, WorkspaceObject } from '../../../types/workspace.ts'
import type { FieldMarksState } from '../../../hooks/useFieldMarks.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'

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
})
