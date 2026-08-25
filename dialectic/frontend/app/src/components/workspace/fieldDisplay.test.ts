import { describe, expect, it } from 'vitest'
import {
  bareMarkId,
  buildObjectTitleMap,
  causalFieldBinding,
  humanizeRelation,
  resolveSubjectLabel,
  sectionMarks,
  tradingDeskBuilderUrl,
} from './fieldDisplay.ts'
import type { FieldMark, WorkspaceObject } from '../../types/workspace.ts'

const baseMark = (overrides: Partial<FieldMark> & { id: string; relation: FieldMark['relation'] }): FieldMark => ({
  room_id: 'r1',
  thread_id: null,
  origin: 'inferred',
  review: 'provisional',
  deliberative_status: 'active',
  subjects: [],
  title: '',
  payload: {},
  supersedes_id: null,
  caused_by_id: null,
  actor_user_id: null,
  provenance: 'field_inference',
  created_at: '2026-08-13T10:00:00Z',
  reviews: [],
  ...overrides,
})

describe('humanizeRelation', () => {
  it('turns a snake_case relation into a sentence fragment', () => {
    expect(humanizeRelation('emerging_position')).toBe('Emerging position')
    expect(humanizeRelation('possible_contradiction')).toBe('Possible contradiction')
  })
})

describe('bareMarkId', () => {
  it('strips the field_mark: prefix', () => {
    expect(bareMarkId('field_mark:abc-123')).toBe('abc-123')
  })
  it('is a no-op on an id with no prefix', () => {
    expect(bareMarkId('abc-123')).toBe('abc-123')
  })
})

describe('causalFieldBinding', () => {
  it('assigns evidence and target by semantic entity, never subject order', () => {
    const causal = baseMark({
      id: 'field_mark:causal', relation: 'context', review: 'confirmed',
      subjects: [
        { entity: 'rooms', id: 'r1', field: 'thesis_node:hormuz:freight-rates' },
        { entity: 'geo_scopes', id: 'scope-1', field: null },
      ],
      payload: { node_label: 'Freight rates', scope_label: 'Strait of Hormuz' },
    })
    expect(causalFieldBinding(causal)).toEqual({
      bookId: 'hormuz',
      nodeId: 'freight-rates',
      nodeLabel: 'Freight rates',
      roomId: 'r1',
      scopeId: 'scope-1',
      scopeLabel: 'Strait of Hormuz',
    })
  })
})

describe('tradingDeskBuilderUrl', () => {
  it('routes the exact encoded book while credentials remain in the fragment', () => {
    expect(tradingDeskBuilderUrl('secret token', 'room/one', 'Hormuz stress?'))
      .toBe('https://td.somacura.org/builder?edit=Hormuz%20stress%3F#dialectic_token=secret+token&dialectic_room=room%2Fone')
  })
})

describe('buildObjectTitleMap / resolveSubjectLabel', () => {
  const object = (entity: string, id: string, title: string): WorkspaceObject => ({
    id: `${entity}:${id}`, kind: 'reading', room_id: 'r1', branch_id: null,
    title, summary: '', status: 'active',
    created_at: 'x', updated_at: 'x',
    provenance: { origin: 'human', actor_user_id: null, detail: null },
    relationships: [], available_actions: [], review_state: 'none',
    source_entity: [{ entity, id, field: null }], source_event: null,
  })

  it('resolves a subject to the title of the object that owns it', () => {
    const titles = buildObjectTitleMap([object('reading_items', 'r-1', 'The article')])
    expect(resolveSubjectLabel({ entity: 'reading_items', id: 'r-1', field: null }, titles))
      .toBe('The article')
  })

  it('falls back to a generic phrase when the row is outside the projection', () => {
    const titles = buildObjectTitleMap([])
    expect(resolveSubjectLabel({ entity: 'messages', id: 'm-1', field: null }, titles))
      .toBe('a message')
  })

  it('indexes every twin coordinate to the same title (the twin rule)', () => {
    const reading = object('reading_items', 'r-1', 'The article')
    reading.source_entity.push({ entity: 'memories', id: 'mem-1', field: 'twin' })
    const titles = buildObjectTitleMap([reading])
    expect(resolveSubjectLabel({ entity: 'memories', id: 'mem-1', field: null }, titles))
      .toBe('The article')
  })
})

describe('sectionMarks', () => {
  it('groups marks into the eight bands by relation', () => {
    const marks = [
      baseMark({ id: 'field_mark:1', relation: 'emerging_position', title: 'Rates will fall' }),
      baseMark({ id: 'field_mark:2', relation: 'unanswered_question', title: 'When?' }),
    ]
    const { bySection } = sectionMarks(marks)
    expect(bySection.get('positions')?.map((r) => r.mark.id)).toEqual(['field_mark:1'])
    expect(bySection.get('questions')?.map((r) => r.mark.id)).toEqual(['field_mark:2'])
    expect(bySection.get('claims')).toEqual([])
  })

  it('never re-sorts — preserves the backend anchor order within a section', () => {
    // Deliberately NOT in created_at order, mirroring a backend response
    // that has already applied the anchor sort — this function must not
    // second-guess it.
    const marks = [
      baseMark({ id: 'field_mark:z', relation: 'claim_group', title: 'Z', created_at: '2026-08-01T00:00:00Z' }),
      baseMark({ id: 'field_mark:a', relation: 'claim_group', title: 'A', created_at: '2026-08-10T00:00:00Z' }),
    ]
    const { bySection } = sectionMarks(marks)
    expect(bySection.get('claims')?.map((r) => r.mark.title)).toEqual(['Z', 'A'])
  })

  it('folds a corrected mark into its successor\'s history, at the successor\'s row', () => {
    const original = baseMark({
      id: 'field_mark:orig', relation: 'claim_group', title: 'First cut', review: 'superseded',
    })
    const replacement = baseMark({
      id: 'field_mark:new', relation: 'claim_group', title: 'Corrected cut',
      supersedes_id: 'orig' as unknown as FieldMark['supersedes_id'],
    })
    const { bySection } = sectionMarks([original, replacement])
    const rows = bySection.get('claims') ?? []
    // Only ONE visible row — the ancestor is not a row of its own.
    expect(rows.map((r) => r.mark.title)).toEqual(['Corrected cut'])
    expect(rows[0].history.map((m) => m.title)).toEqual(['First cut'])
  })

  it('gives a bare-superseded mark (no successor) its own collapsed row, never dropping it', () => {
    const bareRetired = baseMark({
      id: 'field_mark:retired', relation: 'unanswered_question', title: 'Already answered',
      review: 'superseded',
    })
    const { bySection, orphans } = sectionMarks([bareRetired])
    expect(bySection.get('questions')).toEqual([])
    expect(orphans.get('questions')?.map((o) => o.mark.title)).toEqual(['Already answered'])
  })

  it('nests a supports mark under its resolved subject rather than giving it a row', () => {
    const claim = baseMark({ id: 'field_mark:claim', relation: 'claim_group', title: 'Rates fall' })
    const support = baseMark({
      id: 'field_mark:sup', relation: 'supports', title: '',
      subjects: [{ entity: 'field_marks', id: 'claim', field: null }],
    })
    const { bySection } = sectionMarks([claim, support])
    const claimsRows = bySection.get('claims') ?? []
    expect(claimsRows).toHaveLength(1)
    expect(claimsRows[0].nested).toHaveLength(1)
    expect(claimsRows[0].nested[0].label).toMatch(/supports/i)
    // The tensions section (where "challenges" lives) must not also carry it.
    expect(bySection.get('tensions')).toEqual([])
  })

  it('falls back an unresolvable challenges mark into Tensions rather than dropping it', () => {
    const orphanChallenge = baseMark({
      id: 'field_mark:chal', relation: 'challenges', title: 'A stray challenge',
      subjects: [{ entity: 'messages', id: 'm-1', field: null }],
    })
    const { bySection } = sectionMarks([orphanChallenge])
    expect(bySection.get('tensions')?.map((r) => r.mark.id)).toEqual(['field_mark:chal'])
  })

  it('renders a causal support as evidence instead of subject-order nesting', () => {
    const causal = baseMark({
      id: 'field_mark:causal', relation: 'supports',
      subjects: [
        { entity: 'rooms', id: 'r1', field: 'thesis_node:hormuz:node-1' },
        { entity: 'geo_scopes', id: 'scope-1', field: null },
      ],
      payload: { node_label: 'Shipping chokepoint', scope_label: 'Strait of Hormuz' },
    })
    const { bySection } = sectionMarks([causal])
    expect(bySection.get('evidence')?.map((row) => row.mark.id)).toEqual(['field_mark:causal'])
  })
})
