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

// Release 2 makes Bench, Library and Ledger real. Each is backed by a
// population that actually exists in production -- 5 rooms hold a thesis, 3
// hold readings, 8 hold memories -- and each recomposes a panel that already
// worked rather than rebuilding a workflow beside it.
//
// Judgment, Brief, Focus and Current stay in the approved NAME space and out
// of this list on purpose: production holds zero commitments, zero
// proposals and zero research briefs, so every one of them would render an
// empty scene in every room, and Focus is a STATE, not a scene at all
// (§5.2) -- a permanent Focus tab is exactly the "generic permanent tab"
// design v2 §7.4 says Focus replaces. WHICH scenes a given destination may
// show is scenesForDestination() in lib/workspaceRoute.ts -- one definition,
// read by both the router and the frame.
//
// Field joins this list in Release 3 (§5.2): FieldScene.tsx renders a real
// projection with its own teaching empty state, so it is no longer an
// approved-but-unbuilt name.
export const IMPLEMENTED_WORKSPACE_SCENES = [
  'house',
  'record',
  'bench',
  'field',
  'library',
  'ledger',
  'atlas',
] as const

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
  'field_mark',
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

// ---------------------------------------------------------------------------
// The proposal envelope (design v2 §8.3–8.4)
//
// Mirrors proposal_envelope.ProposalEnvelope. Five different proposal shapes
// live in message metadata today, each with its own relay. One envelope so a
// surface can teach the trust rule once -- "Dialectic can prepare the move, a
// human makes it real" -- instead of five unrelated exceptions.
//
// READS ONLY. Accepting still goes to the relay that owns the write; the
// envelope names the action, it never performs it.
//
// Pinned to the backend by dialectic/tests/test_workspace_contract.py, field
// names and vocabularies alike.
// ---------------------------------------------------------------------------

export const PROPOSAL_KINDS = [
  'prediction_draft',
  'thesis_proposal',
  'thesis_draft',
  'commitment_proposal',
  'reading_draft',
  'prediction_resolution',
] as const

export type ProposalKind = (typeof PROPOSAL_KINDS)[number]

/** The visible lifecycle. `failed` cannot come from a read: on a relay failure
 *  the stored flag deliberately stays false so a retry is a fresh accept, which
 *  makes failure a state THIS side holds. It is in the vocabulary because
 *  dropping it is how a failed write becomes an invisible one (§5.1, §9.3). */
export const PROPOSAL_STATUSES = [
  'proposed',
  'accepted',
  'dismissed',
  'superseded',
  'expired',
  'failed',
] as const

export type ProposalStatus = (typeof PROPOSAL_STATUSES)[number]

export const PROPOSAL_ACTIONS = [
  'accept',
  'dismiss',
  'inspect',
  'open_thesis',
] as const

export type ProposalAction = (typeof PROPOSAL_ACTIONS)[number]

/** metadata slot → normalized kind. The one mapping: the backend reads this
 *  same table, and the contract test fails if the two drift. */
export const PROPOSAL_SLOTS: Record<string, ProposalKind> = {
  proposal: 'prediction_draft',
  thesis_proposal: 'thesis_proposal',
  reading_proposal: 'reading_draft',
  resolution_proposal: 'prediction_resolution',
}

/** The one slot holding a LIST — the detector may hoist up to three. */
export const PROPOSAL_LIST_SLOT = 'commitment_proposals'
export const PROPOSAL_LIST_KIND: ProposalKind = 'commitment_proposal'

export interface ProposalEnvelope {
  id: string
  proposal_kind: ProposalKind
  source_message_id: string
  room_id: string
  branch_id: string | null
  created_by: string | null
  created_at: string
  rationale: string
  payload: Record<string, unknown>
  status: ProposalStatus
  accepted_by: string | null
  accepted_at: string | null
  target_object: string | null
  available_actions: ProposalAction[]
}

export interface ProposalEnvelopeProjection {
  generated_at: string
  room_id: string
  proposals: ProposalEnvelope[]
}

// ---------------------------------------------------------------------------
// The Field (design v2 §14) -- dialectic/field_marks.py
//
// Mirrors field_marks.py's models and vocabularies. field_marks is a
// proofreader's-marks metaphor over one append-only table (migration 017):
// Dialectic pencils in provisional structure -- a support, a contradiction,
// an open question -- and a human's confirm/contest/correct restyles the
// mark rather than rewriting it (§1.10). `review` is DERIVED server-side
// (never a stored column read verbatim); this side never re-derives it.
//
// Pinned to the backend by dialectic/tests/test_workspace_contract.py, same
// as the workspace-object and proposal-envelope shapes above -- order too,
// not just membership, since these render as switch arms and section lists.
// ---------------------------------------------------------------------------

// §14.3's ten low-risk automatic kinds, with support/challenge split into two
// directed relations -- eleven total. §14.4's human-ratified judgments are
// deliberately NOT here: none of them is a member, which is what makes them
// structurally unwritable by inference (field_marks.py's own guard comment).
export const FIELD_RELATIONS = [
  'contribution_type',
  'claim_group',
  'supports',
  'challenges',
  'repeated_definition',
  'possible_contradiction',
  'emerging_position',
  'evidence_attachment',
  'branch_candidate',
  'unanswered_question',
  'candidate_synthesis',
] as const

export type FieldRelation = (typeof FIELD_RELATIONS)[number]

export const FIELD_ACTIONS = [
  'confirm',
  'contest',
  'correct',
  'supersede',
  'split',
  'merge',
] as const

export type FieldAction = (typeof FIELD_ACTIONS)[number]

export const FIELD_ORIGINS = [
  'explicit',
  'inferred',
] as const

export type FieldOrigin = (typeof FIELD_ORIGINS)[number]

/** The independent REVIEW axis (§1.3, §14.2) -- never conflated with
 *  deliberative_status, and never implying the marked proposition is true. */
export const FIELD_REVIEW_STATES = [
  'provisional',
  'confirmed',
  'contested',
  'superseded',
] as const

export type FieldReviewState = (typeof FIELD_REVIEW_STATES)[number]

export const FIELD_DELIBERATIVE_STATUSES = [
  'active',
  'accepted',
  'rejected',
  'resolved',
  'withdrawn',
] as const

export type FieldDeliberativeStatus = (typeof FIELD_DELIBERATIVE_STATUSES)[number]

/** Exactly where a mark points. Mirrors field_marks.FieldSubjectRef, which
 *  deliberately mirrors WorkspaceSourceRef's shape without importing it (the
 *  backend's own module docstring explains why: the opposite dependency
 *  already exists). Kept as its own interface here for the same reason. */
export interface FieldSubjectRef {
  entity: string
  id: string
  field: string | null
}

/** One human action on a mark. Never itself reviewed -- reviews are the
 *  leaves of the append-only tree, not a target of a target. */
export interface FieldReview {
  id: string
  action: FieldAction
  actor_user_id: string | null
  note: string | null
  created_at: string
}

/** One relation-kind row, exactly as a surface renders it. `review` is
 *  DERIVED server-side (never a stored column) -- see field_marks.py's
 *  `_derive_review_state`. `supersedes_id`/`caused_by_id` are bare row ids
 *  (not `field_mark:`-prefixed) because they are foreign keys into this SAME
 *  table, not cross-entity references. */
export interface FieldMark {
  id: string
  room_id: string
  thread_id: string | null
  relation: FieldRelation
  origin: FieldOrigin | null
  review: FieldReviewState
  deliberative_status: FieldDeliberativeStatus
  subjects: FieldSubjectRef[]
  title: string
  payload: Record<string, unknown>
  supersedes_id: string | null
  caused_by_id: string | null
  actor_user_id: string | null
  provenance: string
  created_at: string
  reviews: FieldReview[]
}

export interface FieldProjection {
  generated_at: string
  room_id: string
  marks: FieldMark[]
}

// --- the review write door (api/field.py) -----------------------------------
//
// Not pinned by test_workspace_contract.py (that file pins the READ shapes
// above) -- these are request/response payloads for lib/api.ts's
// postFieldReview, kept here beside the shapes they carry rather than as
// anonymous inline types.

export interface FieldReplacementRequest {
  relation: FieldRelation
  subjects: FieldSubjectRef[]
  title?: string
  payload?: Record<string, unknown>
}

export interface FieldReviewRequest {
  action: FieldAction
  note?: string | null
  replacement?: FieldReplacementRequest
  replacements?: FieldReplacementRequest[]
  merge_ids?: string[]
}

export interface FieldReviewResponse {
  review: FieldReview
  replacements: FieldMark[]
  mark: FieldMark
}
