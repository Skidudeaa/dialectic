// The Long Way organ: the shapes the backend serves and the chart consumes.
// Mirrors `tools/longway.py chart_data()` in /root/theLongWay plus the fields
// only the server knows (room, rooms, vehicles' fixes, fixes_state). The
// contract is docs/LONGWAY_ORGAN.md §5; change both together.

export type Ink = 'pencil' | 'dotted' | 'dashed' | 'heavy' | 'contradicted'
export type EvidenceStatus = 'unverified' | 'verified' | 'contradicted' | 'stale'
export type JourneyKind = 'candidate' | 'trip'

/** Records store [lat, lon, label]; GeoJSON wants [lon, lat]. */
export type RoutePoint = [number, number, string]

export interface Season {
  good: number[]
  possible: number[]
  avoid: number[]
  /** "hypothesis" is an unchecked estimate; otherwise evidence ids from the journey's ledger. */
  basis: 'hypothesis' | string[]
  note?: string | null
}

export interface Segment {
  from: string
  to: string
  ink: Ink
  basis: string[]
}

export interface EvidenceRow {
  claim: string
  status: EvidenceStatus
  publisher: string | null
  url: string | null
  checked_at: string | null
  scope: string | null
  recheck_days?: number | null
  /** checked_at plus recheck_days is before today: drawn paled, never alerted. */
  faded: boolean
}

export interface Journey {
  slug: string
  kind: JourneyKind
  title: string
  where: string | null
  status: string
  feasibility: string | null
  judgment: string | null
  season: Season | null
  days: [number, number] | null
  route: RoutePoint[]
  pull: string
  journey: string
  questions: string[]
  segments: Segment[]
  /** Trips only. */
  window?: { start: string; end: string } | null
}

export interface Fix {
  lat: number
  lon: number
  /** ISO time of the vehicle's own broadcast. */
  at: string
  age_min: number
  sog?: number | null
  status?: string | null
  place?: string | null
  source: 'ais' | 'amtrak'
}

export interface VehicleLeg {
  from: string
  to: string
  points: [[number, number] | null, [number, number] | null]
}

export interface Vehicle {
  journey: string
  name: string
  kind: 'ship' | 'ferry' | 'boat' | 'train'
  operator?: string
  mmsi?: string
  imo?: string
  amtrak?: string
  timetable?: string
  note?: string
  /** Identifiers backed by evidence ids rather than a hypothesis. */
  sourced: boolean
  legs: VehicleLeg[]
  /** Presence and movement only; never a timetable. null when never heard. */
  fix: Fix | null
  heard: boolean
}

export interface FixesState {
  written: string | null
  stale: boolean
  why: string | null
}

export interface RoomLink {
  id: string
  name: string
  linked_journey: string | null
}

export interface ChartProjection {
  generated: string
  fetched_at: string
  name: string
  room: { id: string; linked_journey: string | null; is_home: boolean }
  rooms: RoomLink[]
  journeys: Journey[]
  sources: Record<string, Record<string, EvidenceRow>>
  vehicles: Vehicle[]
  fixes_state: FixesState
}

export interface ChartProps {
  data: ChartProjection
  /** The room's journey: everything else is dimmed. null in the house. */
  focus: string | null
  /** The journey whose stops are labelled and whose legs carry the halo. */
  selected: string | null
  /** "Without the mythology": hide pencil and dotted. */
  myth: boolean
  onSelectJourney: (slug: string | null) => void
  onSelectLeg: (slug: string, index: number) => void
  onDiscussLeg?: (slug: string, index: number) => void
  reducedMotion?: boolean
}

export interface JourneyDetail extends Journey {
  dossier: string
  evidence: Array<EvidenceRow & { id: string }>
  vehicles: Vehicle[]
  plan?: { established: string; undecided: string } | null
}

export interface EvidenceProposal {
  id: string
  room_id: string
  created_at: string
  candidate: string
  url: string
  claim: string
  scope: string
  support: string | null
  publisher: string | null
  published_at: string | null
  proposed_by: 'llm' | 'human'
  proposer_user_id: string | null
  source_message_id: string | null
  /** Derived from field marks on this proposal. */
  review: 'proposed' | 'confirmed' | 'contested' | 'corrected'
  written_sid: string | null
  written_at: string | null
  written_commit: string | null
}

export interface Confirmation {
  id: string
  room_id: string
  member_id: string
  member_name: string
  binds: string
  confirmed_on: string
  channel: string
  recorded_by: string
  created_at: string
}

export interface DispatchMetadata {
  journey: string | null
  week_of: string
}

export interface AnchorMetadata {
  journey: string
  leg: number
}
