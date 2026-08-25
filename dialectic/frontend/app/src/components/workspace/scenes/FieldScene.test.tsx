import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FieldScene } from './FieldScene'
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

const noObjects: WorkspaceObjectsState = { status: 'ready', objects: [], generatedAt: 'x', retry: () => {} }

afterEach(() => {
  useAppStore.setState({ accessToken: null })
})

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

  it('says what a mark IS on the populated scene, not only on the empty one', () => {
    // The defect this closes: every word explaining a field mark lived in the
    // empty state, which is the one screen a room with 85 marks never sees.
    // Production had 85 marks and zero human reviews, ever.
    const state: FieldMarksState = {
      status: 'ready', generatedAt: 'x', refresh: () => {},
      marks: [mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'Rates fall' })],
    }
    render(<FieldScene state={state} objects={noObjects} onOpen={vi.fn()} />)
    const lede = document.querySelector('.field-lede')
    expect(lede?.textContent).toMatch(/provisional, and not conclusions/i)
    expect(lede?.textContent).toMatch(/confirm or contest/i)
    // And the definition is reachable, not assumed — the glossary marker is a
    // real button, never a hover-only `title`.
    expect(screen.getByRole('button', { name: 'Field marks' })).toBeInTheDocument()
  })

  it('does not promise a tap the scene cannot honour', () => {
    // Without `onOpen` the rows are not tappable. "Tap a row to open it" would
    // then be advertising a door that does not exist.
    const state: FieldMarksState = {
      status: 'ready', generatedAt: 'x', refresh: () => {},
      marks: [mark({ id: 'field_mark:1', relation: 'emerging_position', title: 'Rates fall' })],
    }
    render(<FieldScene state={state} objects={noObjects} />)
    const lede = document.querySelector('.field-lede')
    expect(lede?.textContent).not.toMatch(/tap a row/i)
    expect(lede?.textContent).toMatch(/under the message that earned the mark/i)
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

  it('shows an adjudicated causal binding and its authenticated Builder route', () => {
    useAppStore.setState({ accessToken: 'session-token' })
    const causal = mark({
      id: 'field_mark:causal', relation: 'challenges', title: 'Hormuz challenges freight',
      review: 'contested',
      subjects: [
        { entity: 'rooms', id: 'r1', field: 'thesis_node:hormuz:freight-rates' },
        { entity: 'geo_scopes', id: 'scope-1', field: null },
      ],
      payload: { node_label: 'Freight rates', scope_label: 'Strait of Hormuz' },
    })
    render(<FieldScene
      state={{ status: 'ready', generatedAt: 'x', refresh: () => {}, marks: [causal] }}
      objects={noObjects}
    />)

    expect(screen.getByText('Strait of Hormuz')).toBeInTheDocument()
    expect(screen.getByText('Challenges')).toBeInTheDocument()
    expect(screen.getByText('Freight rates')).toBeInTheDocument()
    expect(screen.getByText('contested')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open thesis in Builder' })).toHaveAttribute(
      'href',
      'https://td.somacura.org/builder?edit=hormuz#dialectic_token=session-token&dialectic_room=r1',
    )
  })
})
