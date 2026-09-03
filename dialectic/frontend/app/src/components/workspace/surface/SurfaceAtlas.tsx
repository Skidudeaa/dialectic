import type { JSX } from 'react'
import type { GeoScope, WorldObservation, WorldObservationCount } from '../../../types/geo.ts'
import { geometryBBox, geometryPath, makeProjector, unionBBox } from './geoProject.ts'
import type { BBox, GeoJSONGeometry } from './geoProject.ts'
import './SurfaceAtlas.css'

/**
 * SurfaceAtlas — the working surface's inline 2-D map (World Lens: the
 * surface mocks, 2026-09-02). WHY no Cesium: the surface renders inline
 * beside the transcript, at conversation scale, where a lazy 4.2 MB globe
 * chunk and network tiles would be the wrong tool — this is an SVG built
 * from geometry the room already holds (`GeoScope`) and observations the
 * room already recorded (`WorldObservation`), nothing fetched, nothing
 * animated. `World ↗` (via `onOpenWorld`) is the door to the real globe when
 * a viewer wants it.
 */
export interface SurfaceAtlasProps {
  scopes: GeoScope[]
  observations: WorldObservation[]
  counts: WorldObservationCount[]
  /** A selected observation id. */
  selectedId: string | null
  onSelect: (observation: WorldObservation | null) => void
  /** Renders a "World ↗" button when present. */
  onOpenWorld?: () => void
  /** Hours the observations window covers, for the header line (default 48). */
  hours?: number
  /** The observations fetch's own state — a loading or failed read must not
   *  render as "no fire cells" (design v2 §7.5). */
  contactsStatus?: 'loading' | 'ready' | 'unavailable'
}

const SVG_WIDTH = 720
const SVG_HEIGHT = 300
const PADDING = 28
const GRATICULE_STEP = 2
const LABEL_CHAR_WIDTH = 7.2
const LABEL_HEIGHT = 16
const LABEL_GUTTER = 4
const LABEL_OFFSETS: ReadonlyArray<readonly [number, number]> = [
  [0, -10], [0, 18], [0, -30], [0, 38], [38, -10], [-38, -10], [48, 20], [-48, 20],
]
// Only reached when every scope's geometry is unwalkable (malformed rows) —
// a small, arbitrary box so the projector still has a valid bbox to fit.
const FALLBACK_BBOX: BBox = [-1, -1, 1, 1]

interface LabelBox { left: number; top: number; right: number; bottom: number }
interface ScopeLabelPlacement { x: number; y: number; cx: number; cy: number }

function labelBox(label: string, x: number, y: number): LabelBox {
  const halfWidth = Math.min(132, Math.max(22, label.length * LABEL_CHAR_WIDTH * 0.5))
  return {
    left: x - halfWidth - LABEL_GUTTER,
    top: y - LABEL_HEIGHT + 2 - LABEL_GUTTER,
    right: x + halfWidth + LABEL_GUTTER,
    bottom: y + 3 + LABEL_GUTTER,
  }
}

function boxesOverlap(a: LabelBox, b: LabelBox): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
}

/** Deterministic label placement for a cramped inline atlas. Broad regions
 *  get first choice; narrow TSS/lane labels take the next clear slot. The
 *  geometry and scope order are untouched — this only prevents two names at
 *  near-identical centroids from painting over one another. */
function placeScopeLabels(
  scopes: GeoScope[],
  project: ReturnType<typeof makeProjector>,
): Map<string, ScopeLabelPlacement> {
  const occupied: LabelBox[] = []
  const placements = new Map<string, ScopeLabelPlacement>()
  const ordered = scopes
    .map((scope, index) => ({ scope, index, isLane: /\b(?:lane|tss)\b/i.test(scope.label) }))
    .sort((a, b) => Number(a.isLane) - Number(b.isLane) || a.index - b.index)

  for (const { scope, isLane } of ordered) {
    const [cx, cy] = project(scope.centroid[0], scope.centroid[1])
    let chosen: { x: number; y: number; box: LabelBox } | null = null
    for (const [dx, dy] of LABEL_OFFSETS) {
      const width = Math.min(264, Math.max(44, scope.label.length * LABEL_CHAR_WIDTH))
      const x = Math.max(width / 2 + 8, Math.min(SVG_WIDTH - width / 2 - 8, cx + dx))
      const y = Math.max(18, Math.min(SVG_HEIGHT - 8, cy + dy))
      const box = labelBox(scope.label, x, y)
      if (!occupied.some((other) => boxesOverlap(box, other))) {
        chosen = { x, y, box }
        break
      }
    }
    // In a pathological cluster, a secondary lane label yields to the
    // surrounding named regions; primary region labels still remain visible.
    if (!chosen && isLane) continue
    const fallback = chosen ?? (() => {
      const width = Math.min(264, Math.max(44, scope.label.length * LABEL_CHAR_WIDTH))
      const x = Math.max(width / 2 + 8, Math.min(SVG_WIDTH - width / 2 - 8, cx))
      const y = Math.max(18, Math.min(SVG_HEIGHT - 8, cy - 10))
      return { x, y, box: labelBox(scope.label, x, y) }
    })()
    occupied.push(fallback.box)
    placements.set(scope.id, { x: fallback.x, y: fallback.y, cx, cy })
  }
  return placements
}

function pointCoords(geometry: GeoJSONGeometry | null | undefined): [number, number] | null {
  if (!geometry || geometry.type !== 'Point') return null
  const c = geometry.coordinates
  if (Array.isArray(c) && typeof c[0] === 'number' && typeof c[1] === 'number') return [c[0], c[1]]
  return null
}

function graticuleValues(min: number, max: number, step: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return []
  const start = Math.ceil(min / step) * step
  const values: number[] = []
  for (let v = start; v <= max; v += step) values.push(v)
  return values
}

function detailNumber(details: Record<string, unknown>, key: string): number | null {
  const value = details[key]
  return typeof value === 'number' ? value : null
}

function fireRadius(details: Record<string, unknown>): number {
  const frp = detailNumber(details, 'frp') ?? 0
  return Math.min(2 + Math.sqrt(Math.max(frp, 0)) * 0.9, 12)
}

/** The one place fire/aircraft/quake tooltip text is built — every marker
 *  kind, plus the fires-only FRP/confidence/baseline clause. */
function markerTitle(obs: WorldObservation): string {
  let title = `${obs.label} · ${obs.layer} · ${obs.scope_label}`
  if (obs.layer === 'fires') {
    const frp = detailNumber(obs.details, 'frp')
    const confidence = typeof obs.details.confidence === 'string' ? obs.details.confidence : 'unknown'
    const baselineDays = detailNumber(obs.details, 'baseline_days')
    const novelPart = obs.details.novel === true ? 'NEW vs 30-day baseline' : `recurring ${baselineDays ?? '?'}d`
    title += ` · FRP ${frp ?? '?'} MW · ${confidence} · ${novelPart}`
  }
  return title
}

/** counts drives the header, never the raw observation list — a room's Bench
 *  World strip uses the same per-scope aggregate (WorldStrip.tsx) so a
 *  window-capped observation list can't undercount. */
function headerLine(
  scopeCount: number, counts: WorldObservationCount[], hours: number,
  contactsStatus: 'loading' | 'ready' | 'unavailable',
): string {
  if (contactsStatus === 'loading') {
    return `Atlas · ${scopeCount} confirmed area${scopeCount === 1 ? '' : 's'} · reading contacts…`
  }
  if (contactsStatus === 'unavailable') {
    return `Atlas · ${scopeCount} confirmed area${scopeCount === 1 ? '' : 's'} · contacts unavailable`
  }
  const fireRows = counts.filter((c) => c.layer === 'fires')
  const fireTotal = fireRows.reduce((sum, c) => sum + c.count, 0)
  const fireNovel = fireRows.reduce((sum, c) => sum + (c.novel ?? 0), 0)
  const hasAircraft = counts.some((c) => c.layer === 'aircraft')
  const aircraftTotal = counts.filter((c) => c.layer === 'aircraft').reduce((sum, c) => sum + c.count, 0)

  let line = `Atlas · ${scopeCount} confirmed area${scopeCount === 1 ? '' : 's'}`
  line += fireTotal > 0
    ? ` · ${fireTotal} fire cells in ${hours}h, ${fireNovel} new`
    : ` · no fire cells in ${hours}h`
  if (hasAircraft) line += ` · ${aircraftTotal} aircraft`
  return line
}

export function SurfaceAtlas(props: SurfaceAtlasProps): JSX.Element {
  const { scopes, observations, counts, selectedId, onSelect, onOpenWorld, hours = 48, contactsStatus = 'ready' } = props

  if (scopes.length === 0) {
    return (
      <div className="surf-atlas">
        <p className="surf-atlas-empty">No geography placed for this room.</p>
      </div>
    )
  }

  const bbox = unionBBox(scopes.map((s) => geometryBBox(s.geometry))) ?? FALLBACK_BBOX
  const project = makeProjector(bbox, SVG_WIDTH, SVG_HEIGHT, PADDING)
  const [minLon, minLat, maxLon, maxLat] = bbox
  const lonLines = graticuleValues(minLon, maxLon, GRATICULE_STEP)
  const latLines = graticuleValues(minLat, maxLat, GRATICULE_STEP)
  const scopeLabels = placeScopeLabels(scopes, project)

  const pointObservations = observations
    .map((obs) => ({ obs, coords: pointCoords(obs.geometry) }))
    .filter((row): row is { obs: WorldObservation; coords: [number, number] } => row.coords !== null)

  const header = headerLine(scopes.length, counts, hours, contactsStatus)

  function selectOrClear(obs: WorldObservation, isSelected: boolean): void {
    onSelect(isSelected ? null : obs)
  }

  return (
    <div className="surf-atlas">
      <div className="surf-atlas-header">
        <span className="surf-atlas-title">{header}</span>
        {onOpenWorld && (
          <button type="button" className="surf-atlas-world-btn" onClick={onOpenWorld}>
            World ↗
          </button>
        )}
      </div>
      <div className="surf-atlas-canvas">
        <svg
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          width="100%"
          preserveAspectRatio="xMidYMid meet"
          className="surf-atlas-svg"
          role="img"
          aria-label={header}
        >
          <g className="surf-atlas-graticule" aria-hidden="true">
            {lonLines.map((lon) => {
              const [x, yTop] = project(lon, minLat)
              const [, yBottom] = project(lon, maxLat)
              return <line key={`lon-${lon}`} x1={x} y1={yTop} x2={x} y2={yBottom} />
            })}
            {latLines.map((lat) => {
              const [xLeft, y] = project(minLon, lat)
              const [xRight] = project(maxLon, lat)
              return <line key={`lat-${lat}`} x1={xLeft} y1={y} x2={xRight} y2={y} />
            })}
          </g>
          <g className="surf-atlas-scopes">
            {scopes.map((scope) => {
              const d = geometryPath(scope.geometry, project)
              const label = scopeLabels.get(scope.id)
              const proposed = scope.authority === 'machine_proposed'
              return (
                <g key={scope.id}>
                  {d && (
                    <path
                      d={d}
                      className={proposed ? 'surf-atlas-scope surf-atlas-scope--proposed' : 'surf-atlas-scope'}
                    />
                  )}
                  {label && (
                    <g className="surf-atlas-scope-label-group">
                      {Math.hypot(label.x - label.cx, label.y - label.cy) > 14 && (
                        <line
                          x1={label.cx}
                          y1={label.cy}
                          x2={label.x}
                          y2={label.y - 5}
                          className="surf-atlas-scope-label-leader"
                        />
                      )}
                      <text x={label.x} y={label.y} className="surf-atlas-scope-label" textAnchor="middle">
                        {scope.label}
                      </text>
                    </g>
                  )}
                </g>
              )
            })}
          </g>
          <g className="surf-atlas-markers">
            {pointObservations.map(({ obs, coords }) => {
              const [x, y] = project(coords[0], coords[1])
              const isSelected = selectedId === obs.id
              const title = markerTitle(obs)
              const isNovelFire = obs.layer === 'fires' && obs.details.novel === true

              let r = 2
              let shapeClassName = 'surf-atlas-dot surf-atlas-dot--other'
              if (obs.layer === 'fires') {
                r = fireRadius(obs.details)
                shapeClassName = isNovelFire
                  ? 'surf-atlas-dot surf-atlas-dot--fires-novel'
                  : 'surf-atlas-dot surf-atlas-dot--fires'
              } else if (obs.layer === 'aircraft') {
                r = 2.2
                shapeClassName = 'surf-atlas-dot surf-atlas-dot--aircraft'
              } else if (obs.layer === 'earthquakes') {
                r = 2 + (detailNumber(obs.details, 'magnitude') ?? 3)
                shapeClassName = 'surf-atlas-ring surf-atlas-ring--earthquakes'
              }

              return (
                <g
                  key={obs.id}
                  role="button"
                  tabIndex={0}
                  aria-label={title}
                  className={['surf-atlas-marker', `surf-atlas-marker--${obs.layer}`, isSelected ? 'is-selected' : '']
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => selectOrClear(obs, isSelected)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      selectOrClear(obs, isSelected)
                    }
                  }}
                >
                  <title>{title}</title>
                  <circle cx={x} cy={y} r={r} className={shapeClassName} />
                  {isNovelFire && <circle cx={x} cy={y} r={r + 3} className="surf-atlas-ring surf-atlas-ring--novel" />}
                  {isSelected && <circle cx={x} cy={y} r={r + 3} className="surf-atlas-halo" />}
                </g>
              )
            })}
          </g>
        </svg>
      </div>
      {observations.length === 0 && contactsStatus === 'ready' && (
        <p className="surf-atlas-quiet">no contacts recorded in {hours}h</p>
      )}
      <p className="surf-atlas-legend">● recurring fire  ◎ new vs 30-day  · aircraft  ○ quake</p>
    </div>
  )
}
