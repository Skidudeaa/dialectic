// The approved scene vocabulary for the living workroom.
//
// WHY two lists: WORKSPACE_SCENES is the full approved NAME space, so a URL
// naming a future scene parses as a known name rather than garbage.
// IMPLEMENTED_WORKSPACE_SCENES is what actually renders today. Keeping them
// separate is what lets an approved-but-unbuilt scene fall back cleanly instead
// of exposing dead UI -- the program forbids shipping a scene name that opens
// nothing.
export const WORKSPACE_SCENES = [
  'house',
  'record',
  'bench',
  'library',
  'ledger',
  'field',
  'focus',
  'judgment',
  'atlas',
] as const

export type WorkspaceScene = (typeof WORKSPACE_SCENES)[number]

export const IMPLEMENTED_WORKSPACE_SCENES = ['house', 'record'] as const

export type ImplementedWorkspaceScene =
  (typeof IMPLEMENTED_WORKSPACE_SCENES)[number]

export interface WorkspaceLocation {
  scene: ImplementedWorkspaceScene
}

export function isWorkspaceScene(value: string | null): value is WorkspaceScene {
  return value !== null
    && (WORKSPACE_SCENES as readonly string[]).includes(value)
}

export function isImplementedWorkspaceScene(
  value: WorkspaceScene | null,
): value is ImplementedWorkspaceScene {
  return value !== null
    && (IMPLEMENTED_WORKSPACE_SCENES as readonly string[]).includes(value)
}

// ---------------------------------------------------------------------------
// The workspace-object contract (design v2 §8.1)
//
// Mirrors workspace_objects.WorkspaceObject. ADAPTERS, NOT A TABLE: every
// object here is a read-only projection of a row that already exists in its
// own store, so a surface can render a reading, a thesis and a proposal
// without learning three schemas.
//
// The two sides are pinned against each other by a real test --
// dialectic/tests/test_workspace_contract.py reads THIS file and compares its
// field names to the Pydantic model's. A field added on one side and not the
// other goes red; a mirror kept by good intentions does not.
// ---------------------------------------------------------------------------

export const WORKSPACE_OBJECT_KINDS = [
  'reading',
  'research_brief',
  'thesis',
  'commitment',
  'proposal',
  'dossier_entry',
  'house_movement',
  'record_event',
] as const

export type WorkspaceObjectKind = (typeof WORKSPACE_OBJECT_KINDS)[number]

/** What a human still owes this object -- deliberately NOT its own lifecycle.
 *  `failed` exists because a human-authorized write that did not complete must
 *  stay visible rather than vanish (§5.1, §8.4). */
export const WORKSPACE_REVIEW_STATES = [
  'none',
  'awaiting_human',
  'accepted',
  'dismissed',
  'resolved',
  'failed',
] as const

export type WorkspaceReviewState = (typeof WORKSPACE_REVIEW_STATES)[number]

export const WORKSPACE_ORIGINS = [
  'human',
  'dialectic',
  'desk',
  'system',
] as const

export type WorkspaceOrigin = (typeof WORKSPACE_ORIGINS)[number]

/** What a surface MAY offer. Descriptive only -- listing an action performs
 *  nothing, and Release 1 adapters write nothing at all. */
export const WORKSPACE_ACTIONS = [
  'open_room',
  'open_branch',
  'open_message',
  'open_source',
  'open_thesis',
  'accept',
  'dismiss',
  'resolve',
  'inspect',
] as const

export type WorkspaceAction = (typeof WORKSPACE_ACTIONS)[number]

/** Exactly where a projection came from. `field` names the slot inside the
 *  row when one row carries several objects (a message with four proposals). */
export interface WorkspaceSourceRef {
  entity: string
  id: string
  field: string | null
}

export interface WorkspaceRelationship {
  relation: string
  entity: string
  id: string
}

export interface WorkspaceProvenance {
  origin: WorkspaceOrigin
  actor_user_id: string | null
  detail: string | null
}

export interface WorkspaceObject {
  id: string
  kind: WorkspaceObjectKind
  room_id: string
  branch_id: string | null
  title: string
  summary: string
  status: string
  created_at: string
  updated_at: string
  provenance: WorkspaceProvenance
  relationships: WorkspaceRelationship[]
  available_actions: WorkspaceAction[]
  review_state: WorkspaceReviewState
  source_entity: WorkspaceSourceRef[]
  source_event: WorkspaceSourceRef | null
}

export interface WorkspaceObjectProjection {
  generated_at: string
  room_id: string
  objects: WorkspaceObject[]
}
