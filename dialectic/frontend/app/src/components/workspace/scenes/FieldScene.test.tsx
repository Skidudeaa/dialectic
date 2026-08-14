import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FieldScene } from './FieldScene'
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

const noObjects: WorkspaceObjectsState = { status: 'ready', objects: [], generatedAt: 'x', retry: () => {} }

describe('FieldScene', () => {
  it('shows loading, never empty, while the fetch is in flight', () => {
    render(<FieldScene state={{ status: 'loading' }} objects={noObjects} />)
    expect(screen.getByTestId('scene-loading')).toBeInTheDocument()
  })

  it('shows the unavailable state, not an empty shelf, on a failed fetch', () => {
    const state: FieldMarksState = { status: 'unavailable', error: 'boom', retry: () => {} }
    render(<FieldScene state={state} objects={noObjects} />)
    expect(screen.getByTestId('scene-unavailable')).toBeInTheDocument()
  })

  it('renders sections in fixed order and every review state carries its text chip', () => {
    const state: FieldMarksState = {
      status: 'ready',
      generatedAt: 'x',
      refresh: () => {},
      marks: [
        mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'Rates fall', review: 'provisional' }),
        mark({ id: 'field_mark:2', relation: 'claim_group', title: 'A claim', review: 'confirmed' }),
        mark({ id: 'field_mark:3', relation: 'possible_contradiction', title: 'A tension', review: 'contested' }),
      ],
    }
    render(<FieldScene state={state} objects={noObjects} />)

    const sectionLabels = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    // Fixed order, and only sections that hold a mark are rendered.
    expect(sectionLabels).toEqual(['Positions', 'Claims', 'Tensions'])

    // No color-only meaning (§17.4): every state's literal word is on screen.
    expect(screen.getByText('provisional')).toBeInTheDocument()
    expect(screen.getByText('confirmed')).toBeInTheDocument()
    expect(screen.getByText('contested')).toBeInTheDocument()
  })

  it('selects a tapped mark into Focus via onOpen — never a direct write', () => {
    const onOpen = vi.fn()
    const theMark = mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'Rates fall' })
    const state: FieldMarksState = { status: 'ready', generatedAt: 'x', refresh: () => {}, marks: [theMark] }
    render(<FieldScene state={state} objects={noObjects} onOpen={onOpen} />)

    fireEvent.click(screen.getByText('Rates fall'))
    expect(onOpen).toHaveBeenCalledWith(theMark)
  })

  it('resolves a subject to its title from the workspace-objects projection, not a raw id', () => {
    const objects: WorkspaceObjectsState = {
      status: 'ready',
      generatedAt: 'x',
      retry: () => {},
      objects: [{
        id: 'reading:r-1', kind: 'reading', room_id: 'r1', branch_id: null,
        title: 'The tariff piece', summary: '', status: 'active',
        created_at: 'x', updated_at: 'x',
        provenance: { origin: 'human', actor_user_id: null, detail: null },
        relationships: [], available_actions: [], review_state: 'none',
        source_entity: [{ entity: 'reading_items', id: 'r-1', field: null }],
        source_event: null,
      } satisfies WorkspaceObject],
    }
    const state: FieldMarksState = {
      status: 'ready', generatedAt: 'x', refresh: () => {},
      marks: [mark({
        id: 'field_mark:1', relation: 'evidence_attachment', title: 'Cites the piece',
        subjects: [{ entity: 'reading_items', id: 'r-1', field: null }],
      })],
    }
    render(<FieldScene state={state} objects={objects} />)
    expect(screen.getByText('The tariff piece')).toBeInTheDocument()
  })
})
