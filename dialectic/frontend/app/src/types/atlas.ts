import type { GeoScope } from './geo'
// Atlas — the caller's own cross-room map (design v2 §22, PLAN.md §5.4).
//
// Mirrors dialectic/atlas_objects.py field-for-field. This file is owned by
// TG-D alone: it has no shared kind-tuple seam with the backend the way
// workspace.ts's WORKSPACE_OBJECT_KINDS does, so there is no order-pinned
// contract test to keep in sync here -- just keep the shapes matching by
// hand when atlas_objects.py's models change.
//
// WHY Atlas is its own file rather than folded into workspace.ts: Atlas
// nodes are NOT workspace objects -- `room` and `branch` are kinds no
// workspace-object adapter produces, and the two projections are fetched,
// capped and fenced completely differently (per-viewer, cross-room, one
// GET with no room token). Two different contracts stay two different
// files, the same reason field_marks.py's FieldMark does not live in
// workspace_objects.py either.

/** The closed node vocabulary — atlas_objects.ATLAS_NODE_KINDS. */
export const ATLAS_NODE_KINDS = [
  'room',
  'branch',
  'thesis',
  'reading',
  'research_brief',
  'commitment',
  'field_mark',
] as const

export type AtlasNodeKind = (typeof ATLAS_NODE_KINDS)[number]

/** The closed edge vocabulary — atlas_objects.ATLAS_EDGE_KINDS.
 *  `contradiction_proxy` is a LABELED DERIVED proxy (supersession chains
 *  with a stated invalidation reason, plus claim_check verdicts where a
 *  matching reading exists) -- never a first-class assertion. */
export const ATLAS_EDGE_KINDS = [
  'branch_genealogy',
  'echo_citation',
  'reading_source',
  'thesis_binding',
  'memory_supersession',
  'contradiction_proxy',
] as const

export type AtlasEdgeKind = (typeof ATLAS_EDGE_KINDS)[number]

/** Exactly which row an edge endpoint names. */
export interface AtlasRef {
  entity: string
  id: string
  field: string | null
}

/** One thing the viewer can navigate to. Node ids REUSE workspace-object id
 *  conventions wherever the same row is projected there too (`reading:<id>`,
 *  `research_brief:<id>`, `thesis:<linked_book_id>`, `commitment:<id>`,
 *  `field_mark:<id>`) — so a tap on an object-kind node can go straight
 *  through the `object` axis (§5.4, §1.18) with no second id scheme to
 *  bridge. `room` and `branch` are Atlas-only kinds and mint their own ids. */
export interface AtlasNode {
  id: string
  kind: AtlasNodeKind
  room_id: string
  branch_id: string | null
  title: string
  summary: string
  status: string
  /** True only for a commitment inside the House's own due window — the
   *  "unresolved work" cross-cutting group is this flag OR kind==='field_mark'. */
  due: boolean
  created_at: string
  updated_at: string
}

export interface AtlasEdge {
  kind: AtlasEdgeKind
  source: AtlasRef
  target: AtlasRef
  label: string
}

export interface AtlasProjection {
  generated_at: string
  nodes: AtlasNode[]
  edges: AtlasEdge[]
  // World Lens: the live geometry in the viewer's eligible rooms, fenced by
  // the same array as every node. Joined to nodes client-side by subject.
  scopes: GeoScope[]
}

/** Object-kind nodes are exactly the kinds workspace_objects.py also
 *  produces -- these are the ones whose id can be handed straight to the
 *  `object` axis. `room` and `branch` navigate by room/thread destination
 *  instead (see AtlasScene's onNavigate). */
const ATLAS_OBJECT_NODE_KINDS: ReadonlySet<AtlasNodeKind> = new Set([
  'thesis', 'reading', 'research_brief', 'commitment', 'field_mark',
])

export function isAtlasObjectNode(node: Pick<AtlasNode, 'kind'>): boolean {
  return ATLAS_OBJECT_NODE_KINDS.has(node.kind)
}
