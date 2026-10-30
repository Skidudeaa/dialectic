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
  /** A pending Scout proposal names this leg: drawn dotted with a "proposed" tag (section 11). */
  proposed?: boolean
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
  rides?: number
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
  /** Pending proposals per journey slug (section 11.4); absent before the Scout slice. */
  proposals?: Record<string, ChartProposal[]>
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

// ---- The Scout goes scouting (docs/LONGWAY_ORGAN.md section 11) -------------

export type QuestionSource = 'human' | 'reaction' | 'message' | 'dossier' | 'scout'

export interface Question {
  id: string
  room_id: string
  journey: string
  text: string
  source: QuestionSource
  source_message_id: string | null
  asked_by: string | null
  asked_by_name?: string | null
  created_at: string
  answered_by_proposal: string | null
  /** Derived from the answering proposal's field marks, when one exists. */
  answer_review?: 'proposed' | 'confirmed' | 'contested' | 'corrected' | null
  closed_at: string | null
}

export interface ScoutRun {
  id: string
  room_id: string
  journey: string
  trigger: 'manual' | 'nightly'
  started_by: string | null
  started_at: string
  finished_at: string | null
  status: 'running' | 'done' | 'failed' | 'killed'
  questions: string[]
  pages_read: number
  searches: number
  proposals: number
  counter_proposals: number
  input_tokens: number
  output_tokens: number
  error: string | null
  /** Present on GET scout/runs/{id} only. */
  log?: Array<Record<string, unknown>>
}

/** The Scout's structured fields on a proposal (section 11.1); null when the passage did not say. */
export interface ProposalScope {
  question_id: string | null
  question_text?: string | null
  run_id: string | null
  search_result_id: string | null
  contradicts: string | null
  applies_from: string | null
  applies_to: string | null
  direction: string | null
  passport: string | null
  vehicle: string | null
  leg_from: string | null
  leg_to: string | null
  load_bearing: boolean
  counter_searched_at: string | null
  /** load_bearing and not yet counter-searched: Confirm is refused with this reason. */
  requires_counter: boolean
  publisher_count: number | null
}

export type ScoutedProposal = EvidenceProposal & ProposalScope

/** What the chart shows of pending proposals: enough for a dotted "proposed" leg and its card. */
export interface ChartProposal {
  id: string
  claim: string
  support: string | null
  review: EvidenceProposal['review']
  url: string
  publisher: string | null
  leg_from: string | null
  leg_to: string | null
  load_bearing: boolean
  requires_counter: boolean
}

export interface ScoutRunMetadata {
  run_id: string
  journey: string
  pages_read: number
  proposals: number
  counter_proposals: number
}

// /root/scratch/20261029-ride/CONTRACT.md. All ride times are ISO UTC.
export type RideState = 'waiting' | 'riding' | 'arrived'
export interface RideVehicle { name: string; kind: string; operator?: string; amtrak?: string; mmsi?: string; imo?: string }
export interface RideFix { lat: number; lon: number; at: string; age_min: number; speed_mph: number | null; heading: string | null; source: 'amtrak' | 'ais' }
export interface RideStop {
  code: string; name: string; km: number | null
  sched_arr: string | null; sched_dep: string | null; arr: string | null; dep: string | null
  estimated: boolean; status: string | null; late_min: number | null
}
export interface RideData {
  trip: { slug: string; title: string }
  rides: { id: string; date: string; state: RideState }[]
  ride: { id: string; date: string; board: string; alight: string; riders: string[]; leg: string | null; leg_ready: boolean; logbook: boolean; vehicle: RideVehicle; state: RideState }
  run: string | null; fix: RideFix | null; fix_unavailable_reason: string | null; km: number | null
  stops: RideStop[]; history: { days: number; at: Record<string, { median: number; worst: number; n: number }> } | null
  track: [string, number, number, number | null][]; fetched_at: string
}
export type KmRow = [number, number, number, number, number, string?, string?]
export interface SightWindow {
  kind: 'view' | 'peak'; name: string; side: 'left' | 'right'; km0: number; km1: number; length_km: number
  minutes: number; t0: number; t1: number; from_code: string; to_code: string; f0: number; f1: number
  start: string; end: string; lat: number; lon: number; best: [number, number]; to?: [number, number]
  light: string; note: string; major?: boolean; covered?: boolean; size?: number; sky?: number | null; peaks?: string[]
}
export interface SignalGap { km0: number; km1: number; length_km: number; minutes: number; near: string; from_code: string; t0: number; t1: number }
export interface GuideEntry { title: string; what?: string; history?: string; img?: string; img_credit?: string; links?: { url: string; label: string; src?: string }[] }
export interface RideLeg {
  id: string; leg: { id: string; kind: string; km: number; built?: string } | null
  sights: { built: string; classes: { label: string; color: string }[]; km: KmRow[]; left: { c: number; pts: [number, number][] }[]; right: { c: number; pts: [number, number][] }[]; sights: SightWindow[]; stations: { code: string; name: string; km: number; lat: number; lon: number; time: string }[]; peaks: { name: string; lat: number; lon: number; ele: number }[] }
  coverage: { classes: { label: string; color: string }[]; segments: { c: number; pts: [number, number][] }[]; measured?: [number, number][][]; gaps: SignalGap[] } | null
  guide: Record<string, GuideEntry> | null
  check: { score: { agree: number; total: number } } | null
}
export interface RidingData { rides: { room_id: string; room_name: string; trip: string | { slug: string; title: string }; ride: { id: string; state: RideState; vehicle: RideVehicle }; fix: RideFix | null; next_stop: { code: string; name: string; est: string | null } | null; late_min: number | null }[] }
