// The World Lens contract (geo_scopes.py, migration 021). Field-for-field
// with the backend; tests/test_geo_scopes.py pins these vocabularies in
// ORDER, not just membership -- they render as legend rows and switch arms.

export const GEO_KINDS = [
  'point',
  'route',
  'polygon',
  'region',
] as const
export type GeoKind = (typeof GEO_KINDS)[number]

// Authority is a column, not a style. `machine_proposed` renders provisional
// and cannot anchor a Field mark until a person confirms it.
export const GEO_AUTHORITIES = [
  'human_confirmed',
  'source_reported',
  'machine_proposed',
] as const
export type GeoAuthority = (typeof GEO_AUTHORITIES)[number]

// The existing evidence statuses plus `confirmed_empty`: we asked, a person
// answered, the answer is none.
export const GEO_SOURCE_STATES = [
  'ok',
  'partial',
  'confirmed_empty',
  'stale',
  'unavailable',
  'rate_limited',
  'not_configured',
] as const
export type GeoSourceState = (typeof GEO_SOURCE_STATES)[number]

export const GEO_REVISION_ACTIONS = [
  'place',
  'propose',
  'confirm',
  'reject',
  'redraw',
  'supersede',
  'ratify',
  'place_signal',
] as const
export type GeoRevisionAction = (typeof GEO_REVISION_ACTIONS)[number]

export const GEO_REVIEW_STATES = [
  'accepted',
  'proposed',
  'rejected',
  'superseded',
] as const
export type GeoReviewState = (typeof GEO_REVIEW_STATES)[number]

export const GEO_FRESHNESS_STATES = [
  'current',
  'stale',
  'expired',
  'unknown',
  'not_applicable',
] as const
export type GeoFreshnessState = (typeof GEO_FRESHNESS_STATES)[number]

export interface GeoSubjectRef {
  entity: string
  id: string
  field?: string | null
}

export interface GeoProvenance {
  provider: string
  acquisition: string
  source_id?: string | null
  url?: string | null
  credit: string
}

export interface GeoFreshness {
  state: GeoFreshnessState
  observed_at?: string | null
  retrieved_at: string
  expires_at?: string | null
}

export interface GeoScope {
  id: string
  room_id: string
  subject: GeoSubjectRef
  kind: GeoKind
  geometry: { type: string; coordinates: unknown }
  label: string
  authority: GeoAuthority
  provenance: GeoProvenance
  source_state: GeoSourceState
  revision_action: GeoRevisionAction
  review_note?: string | null
  review_state: GeoReviewState
  freshness: GeoFreshness
  centroid: [number, number]
  observed_at?: string | null
  retrieved_at: string
  expires_at?: string | null
  confirmed_by?: string | null
  confirmed_at?: string | null
  supersedes_id?: string | null
  created_by?: string | null
  created_at: string
}

/** A current provider observation. Unlike GeoScope, this object is ephemeral,
 * server-owned, and never opens Focus or accepts geometry from the client. */
export interface WorldSignal {
  id: string
  provider: string
  source_id: string
  room_id: string
  layer: string
  kind: GeoKind
  geometry: { type: string; coordinates: unknown }
  provenance: GeoProvenance
  source_state: GeoSourceState
  freshness: GeoFreshnessState
  coverage: string
  observed_at?: string | null
  retrieved_at: string
  expires_at?: string | null
  label: string
  details: Record<string, unknown>
}

/** Provider snapshot state stays separate from each observation's state. */
export interface WorldSignalSource {
  provider: string
  /** Only the intersection of this source's configured rooms and the Atlas
   * viewer's eligible-room fence. */
  configured_room_ids: string[]
  source_state: GeoSourceState
  freshness: GeoFreshnessState
  coverage: string
  observed_at?: string | null
  retrieved_at: string
  expires_at?: string | null
  signal_count: number
}

export interface WorldSignalSources {
  status: 'configured' | 'not_configured'
  sources: WorldSignalSource[]
}

export interface GeoProjection {
  generated_at: string
  room_id: string
  scopes: GeoScope[]
}

export interface GeoSubjectDestination {
  room_id: string
  thread_id?: string | null
  message_id?: string | null
  object_id?: string | null
}

export interface GeoScopeReview {
  root_id: string
  current: GeoScope
  lineage: GeoScope[]
  subject_destination: GeoSubjectDestination
}
