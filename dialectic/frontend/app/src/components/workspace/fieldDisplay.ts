import type { FieldMark, FieldRelation, FieldSubjectRef, WorkspaceObject } from '../../types/workspace.ts'
import './fieldDisplay.css'

/**
 * Shared rendering helpers for the Field (FieldScene) and Focus
 * (components/workspace/focus/*) -- one place for the vocabulary→label
 * humanizer and subject-title resolution, so the two surfaces that both
 * render a FieldMark cannot quietly drift into different words for the
 * same state. The review-state CHIP itself lives in ReviewChip.tsx, a
 * separate file: this one is pure TS (constants and functions only) so
 * react-refresh's "a file exports either components or non-components, not
 * both" rule stays satisfied for every file that imports from it.
 */

/** `emerging_position` -> `Emerging position`. A function, not a hardcoded
 *  map: field_marks.py documents FIELD_RELATIONS as free to grow, and a map
 *  would need a matching new entry on every addition. */
export function humanizeRelation(relation: string): string {
  const spaced = relation.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A stable, client-side title lookup over ONE already-fetched projection --
 *  "no second projection" (§5.2). Keyed by the exact `entity:id` coordinate
 *  field_marks.py's subject refs use (the same strings workspace_objects.py
 *  already writes into `source_entity`: "reading_items", "memories",
 *  "commitments", "messages", "field_marks" -- verified against both
 *  modules, not assumed). A WorkspaceObject can carry several source_entity
 *  refs (the twin rule), so every one of them is indexed to the SAME title —
 *  a mark that names either half of a twin still resolves.
 */
export function buildObjectTitleMap(objects: WorkspaceObject[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const object of objects) {
    for (const ref of object.source_entity) {
      map.set(`${ref.entity}:${ref.id}`, object.title)
    }
  }
  return map
}

/** Same coordinate index as buildObjectTitleMap, but keeping the whole
 *  WorkspaceObject rather than just its title -- Focus's Sources list needs
 *  `branch_id` too, to navigate to what a mark's subject actually names
 *  (FocusSurface.tsx). Kept as a second small function rather than
 *  generalizing the title map, so a caller that only needs a title (the
 *  common case, FieldScene's row rendering) is not forced to hold every
 *  object in memory it never reads past `.title`. */
export function buildObjectByCoordinate(objects: WorkspaceObject[]): Map<string, WorkspaceObject> {
  const map = new Map<string, WorkspaceObject>()
  for (const object of objects) {
    for (const ref of object.source_entity) {
      map.set(`${ref.entity}:${ref.id}`, object)
    }
  }
  return map
}

/** Resolve one subject ref to display text. Falls back to a generic phrase
 *  when the referenced row was not in the projection this Map was built
 *  from (e.g. a message outside the Record's cap) -- never a raw uuid,
 *  which would read as a bug rather than as "just not shown here". */
export function resolveSubjectLabel(
  ref: FieldSubjectRef,
  titles: Map<string, string>,
): string {
  const known = titles.get(`${ref.entity}:${ref.id}`)
  if (known) return known
  const kind = ref.entity === 'field_marks' ? 'mark' : ref.entity.replace(/_/g, ' ').replace(/s$/, '')
  return `a ${kind}`
}

/** field_mark:<uuid> -> <uuid>. supersedes_id/caused_by_id and a
 *  `field_marks`-entity subject ref both use the bare form (FieldMark's own
 *  doc comment); this is the one place that strips the prefix so the two
 *  callers (lineage lookup, subject resolution) cannot drift into different
 *  parsing. */
export function bareMarkId(markId: string): string {
  const idx = markId.indexOf(':')
  return idx === -1 ? markId : markId.slice(idx + 1)
}

export interface CausalFieldBinding {
  bookId: string
  nodeId: string
  nodeLabel: string
  roomId: string
  scopeId: string
  scopeLabel: string
}

/** The server validates these same semantic roles before insert. Re-resolve
 * them here by entity name so reversing JSON subject order can never reverse
 * evidence and target on a surface. Payload labels are historical display
 * only; book/node identity remains the exact room-field grammar. */
export function causalFieldBinding(mark: FieldMark): CausalFieldBinding | null {
  if (!['supports', 'challenges', 'context'].includes(mark.relation)) return null
  if (mark.subjects.length !== 2) return null
  const scopes = mark.subjects.filter((subject) => subject.entity === 'geo_scopes')
  const rooms = mark.subjects.filter((subject) => subject.entity === 'rooms')
  if (scopes.length !== 1 || rooms.length !== 1) return null
  const match = /^thesis_node:([^:]+):([^:]+)$/.exec(rooms[0].field ?? '')
  if (!match) return null
  const nodeLabel = typeof mark.payload.node_label === 'string'
    ? mark.payload.node_label
    : match[2]
  const scopeLabel = typeof mark.payload.scope_label === 'string'
    ? mark.payload.scope_label
    : `GeoScope ${scopes[0].id}`
  return {
    bookId: match[1],
    nodeId: match[2],
    nodeLabel,
    roomId: rooms[0].id,
    scopeId: scopes[0].id,
    scopeLabel,
  }
}

/** Match TradingPanel's fragment-only handoff. The bearer never enters the
 * query string, nginx logs, or Cloudflare request URL. */
export function tradingDeskBuilderUrl(accessToken: string, roomId: string): string {
  const params = new URLSearchParams()
  params.set('dialectic_token', accessToken)
  params.set('dialectic_room', roomId)
  return `https://td.somacura.org/builder#${params.toString()}`
}

/** The eight editorial bands, fixed order, each keyed to the relations it
 *  gathers (§5.2). `supports`/`challenges` are deliberately absent from
 *  every list here -- they never anchor a section of their own. They render
 *  as an indented line under whichever mark they name as a subject
 *  (sectionMarks's nesting pass below), or, when no subject resolves to a
 *  mark in this room, fall back into a section here (see FALLBACK_SECTION
 *  below) so an append-only row can never simply vanish from view. */
export const FIELD_SECTIONS: { key: string; label: string; relations: FieldRelation[] }[] = [
  { key: 'positions', label: 'Positions', relations: ['emerging_position'] },
  { key: 'claims', label: 'Claims', relations: ['claim_group', 'contribution_type'] },
  { key: 'tensions', label: 'Tensions', relations: ['possible_contradiction', 'challenges'] },
  { key: 'questions', label: 'Questions', relations: ['unanswered_question'] },
  { key: 'definitions', label: 'Definitions', relations: ['repeated_definition'] },
  { key: 'evidence', label: 'Evidence', relations: ['evidence_attachment', 'context'] },
  { key: 'syntheses', label: 'Syntheses', relations: ['candidate_synthesis'] },
  { key: 'branches', label: 'Branches', relations: ['branch_candidate'] },
]

/** Where an orphaned supports/challenges mark (subjects that do not resolve
 *  to another mark in this room) lands when it cannot be nested — supports
 *  reads as reinforcing a claim, challenges as a tension. */
export const FALLBACK_SECTION_FOR_NESTED_RELATION: Record<'supports' | 'challenges', string> = {
  supports: 'claims',
  challenges: 'tensions',
}

export interface FieldRow {
  mark: FieldMark
  /** Ancestors this row's lineage superseded, oldest last — rendered behind
   *  a "History" disclosure, never dropped (§5.2's superseded encoding). */
  history: FieldMark[]
  /** supports/challenges marks nested under this row, each already resolved
   *  to a display line ("— supports → <title>"). */
  nested: { mark: FieldMark; label: string }[]
}

/** Marks whose derived review is 'superseded' but that nothing in this
 *  dataset names as an ancestor -- a bare `supersede` retirement, or a
 *  secondary merge source (api/field.py's merge only records ONE
 *  supersedes_id, on the primary target). These have no successor row to
 *  attach a disclosure to, so each renders as its own single-item
 *  disclosure rather than silently disappearing. */
export interface OrphanSupersededRow {
  mark: FieldMark
}

/**
 * Follow a mark's `supersedes_id` chain back through a dataset, oldest last.
 * Shared by `sectionMarks` (the Field scene's history disclosure) and
 * FocusSurface (FocusHistory's lineage), so the two surfaces that both
 * render a mark's supersession trail cannot compute it two different ways.
 */
export function markLineage(mark: FieldMark, all: FieldMark[]): FieldMark[] {
  const byBareId = new Map<string, FieldMark>()
  for (const m of all) byBareId.set(bareMarkId(m.id), m)
  const chain: FieldMark[] = []
  let current = mark
  const seen = new Set<string>([bareMarkId(current.id)])
  while (current.supersedes_id) {
    const prev = byBareId.get(String(current.supersedes_id))
    if (!prev || seen.has(bareMarkId(prev.id))) break
    chain.push(prev)
    seen.add(bareMarkId(prev.id))
    current = prev
  }
  return chain
}

/**
 * Section a room's marks into the eight bands, in the backend's own anchor
 * order (never re-sorted here — §5.2's stable-order rule) with lineage
 * folded into history disclosures and supports/challenges nested under
 * their subject.
 */
export function sectionMarks(marks: FieldMark[]): {
  bySection: Map<string, FieldRow[]>
  orphans: Map<string, OrphanSupersededRow[]>
} {
  // Every mark some later row explicitly names as its ancestor -- these are
  // the ones a "History" disclosure can attach to a live successor. Anything
  // superseded WITHOUT such a claim (see OrphanSupersededRow above) gets its
  // own collapsed row instead.
  const namedAncestors = new Set<string>()
  for (const mark of marks) {
    if (mark.supersedes_id) namedAncestors.add(String(mark.supersedes_id))
  }

  const historyOf = (mark: FieldMark): FieldMark[] => markLineage(mark, marks)

  const byBareId = new Map<string, FieldMark>()
  for (const mark of marks) byBareId.set(bareMarkId(mark.id), mark)

  // Nesting pass: supports/challenges marks attach to whichever OTHER mark
  // they name as a subject, rather than anchoring a row of their own.
  const nestedByParent = new Map<string, { mark: FieldMark; label: string }[]>()
  const orphanNested: FieldMark[] = []
  for (const mark of marks) {
    if (mark.relation !== 'supports' && mark.relation !== 'challenges') continue
    if (causalFieldBinding(mark)) continue
    const resolved = mark.subjects
      .filter((s) => s.entity === 'field_marks')
      .map((s) => byBareId.get(s.id))
      .filter((m): m is FieldMark => Boolean(m))
    if (resolved.length === 0) {
      orphanNested.push(mark)
      continue
    }
    const parent = resolved[0]
    const otherTitle = resolved[1]?.title || mark.title || humanizeRelation(mark.relation)
    const list = nestedByParent.get(bareMarkId(parent.id)) ?? []
    list.push({ mark, label: `${humanizeRelation(mark.relation).toLowerCase()} → ${otherTitle}` })
    nestedByParent.set(bareMarkId(parent.id), list)
  }

  const bySection = new Map<string, FieldRow[]>()
  const orphans = new Map<string, OrphanSupersededRow[]>()
  for (const section of FIELD_SECTIONS) bySection.set(section.key, [])
  for (const key of Object.values(FALLBACK_SECTION_FOR_NESTED_RELATION)) {
    if (!orphans.has(key)) orphans.set(key, [])
  }

  const relationToSection = new Map<FieldRelation, string>()
  for (const section of FIELD_SECTIONS) {
    for (const relation of section.relations) relationToSection.set(relation, section.key)
  }

  for (const mark of marks) {
    const causal = causalFieldBinding(mark)
    if (!causal && (mark.relation === 'supports' || mark.relation === 'challenges')) continue
    const sectionKey = causal ? 'evidence' : relationToSection.get(mark.relation)
    if (!sectionKey) continue // an approved-but-unmapped relation: nothing to lose silently here today
    if (mark.review === 'superseded') {
      if (!namedAncestors.has(bareMarkId(mark.id))) {
        // Orphaned retirement (bare supersede, or a secondary merge source):
        // its own collapsed row, never a silent drop.
        const list = orphans.get(sectionKey) ?? []
        list.push({ mark })
        orphans.set(sectionKey, list)
      }
      // Else: it IS a named ancestor, so it appears inside its successor's
      // history disclosure below — not as a row of its own here.
      continue
    }
    const list = bySection.get(sectionKey) ?? []
    list.push({
      mark,
      history: historyOf(mark),
      nested: nestedByParent.get(bareMarkId(mark.id)) ?? [],
    })
    bySection.set(sectionKey, list)
  }

  for (const mark of orphanNested) {
    const sectionKey = FALLBACK_SECTION_FOR_NESTED_RELATION[mark.relation as 'supports' | 'challenges']
    if (mark.review === 'superseded' && !namedAncestors.has(bareMarkId(mark.id))) {
      const list = orphans.get(sectionKey) ?? []
      list.push({ mark })
      orphans.set(sectionKey, list)
      continue
    }
    if (mark.review === 'superseded') continue
    const list = bySection.get(sectionKey) ?? []
    list.push({ mark, history: historyOf(mark), nested: [] })
    bySection.set(sectionKey, list)
  }

  return { bySection, orphans }
}
