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

export interface GeoProjection {
  generated_at: string
  room_id: string
  scopes: GeoScope[]
}
