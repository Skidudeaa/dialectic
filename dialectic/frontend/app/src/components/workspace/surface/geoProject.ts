// Pure geometry helpers for SurfaceAtlas — no DOM, no network, no Cesium.
// GeoJSON in this repo's `geo_scopes`/`world_observations` contract is
// [lon, lat] order throughout (geo.ts); everything here keeps that order.

export type GeoJSONGeometry = { type: string; coordinates: unknown }

/** [minLon, minLat, maxLon, maxLat]. */
export type BBox = [number, number, number, number]

const WALKABLE_TYPES = new Set([
  'Point',
  'MultiPoint',
  'LineString',
  'MultiLineString',
  'Polygon',
  'MultiPolygon',
])

/** Descends arbitrarily nested coordinate arrays until it hits a [lon, lat]
 *  leaf — one walker serves every geometry type in WALKABLE_TYPES without a
 *  per-type coordinate-depth table. */
function walkCoordinates(coords: unknown, visit: (lon: number, lat: number) => void): void {
  if (!Array.isArray(coords)) return
  if (
    coords.length >= 2
    && typeof coords[0] === 'number'
    && typeof coords[1] === 'number'
  ) {
    visit(coords[0], coords[1])
    return
  }
  for (const c of coords) walkCoordinates(c, visit)
}

/** Walks Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon
 *  coordinates recursively; any other (or missing) geometry — a
 *  GeometryCollection, a malformed row — returns null rather than guessing. */
export function geometryBBox(geometry: GeoJSONGeometry | null | undefined): BBox | null {
  if (!geometry || !WALKABLE_TYPES.has(geometry.type)) return null
  let minLon = Infinity
  let minLat = Infinity
  let maxLon = -Infinity
  let maxLat = -Infinity
  let found = false
  walkCoordinates(geometry.coordinates, (lon, lat) => {
    found = true
    if (lon < minLon) minLon = lon
    if (lat < minLat) minLat = lat
    if (lon > maxLon) maxLon = lon
    if (lat > maxLat) maxLat = lat
  })
  return found ? [minLon, minLat, maxLon, maxLat] : null
}

export function unionBBox(boxes: Array<BBox | null | undefined>): BBox | null {
  const valid = boxes.filter((b): b is BBox => Array.isArray(b))
  if (valid.length === 0) return null
  let [minLon, minLat, maxLon, maxLat] = valid[0]
  for (const [lo, la, hiLon, hiLat] of valid.slice(1)) {
    if (lo < minLon) minLon = lo
    if (la < minLat) minLat = la
    if (hiLon > maxLon) maxLon = hiLon
    if (hiLat > maxLat) maxLat = hiLat
  }
  return [minLon, minLat, maxLon, maxLat]
}

export type Projector = (lon: number, lat: number) => [number, number]

/**
 * Equirectangular projection, x-scale corrected by cos(mean latitude) so a
 * bbox spanning the Gulf (~24-30N) doesn't read squashed east-west. Fit is
 * uniform-scale to the bbox, letterboxed and centered in the width/height
 * canvas — never stretched to fill both axes independently.
 */
export function makeProjector(bbox: BBox, width: number, height: number, padding: number): Projector {
  const [minLon, minLat, maxLon, maxLat] = bbox
  const meanLatRad = ((minLat + maxLat) / 2) * (Math.PI / 180)
  // Guard near-pole degeneracy (cos -> 0) rather than dividing by it.
  const cosLat = Math.max(Math.cos(meanLatRad), 0.05)
  const lonSpan = Math.max(maxLon - minLon, 1e-6)
  const latSpan = Math.max(maxLat - minLat, 1e-6)
  const availW = Math.max(width - 2 * padding, 1)
  const availH = Math.max(height - 2 * padding, 1)
  const scale = Math.min(availW / (lonSpan * cosLat), availH / latSpan)
  const centerLon = (minLon + maxLon) / 2
  const centerLat = (minLat + maxLat) / 2
  const cx = width / 2
  const cy = height / 2
  return (lon: number, lat: number): [number, number] => [
    cx + (lon - centerLon) * cosLat * scale,
    // SVG y grows downward; latitude grows northward.
    cy - (lat - centerLat) * scale,
  ]
}

function ringPath(coords: unknown, project: Projector, close: boolean): string {
  if (!Array.isArray(coords) || coords.length === 0) return ''
  const points: [number, number][] = []
  for (const c of coords) {
    if (Array.isArray(c) && typeof c[0] === 'number' && typeof c[1] === 'number') {
      points.push(project(c[0], c[1]))
    }
  }
  if (points.length === 0) return ''
  const [first, ...rest] = points
  const segments = rest.map(([x, y]) => `L${x.toFixed(2)},${y.toFixed(2)}`)
  const d = `M${first[0].toFixed(2)},${first[1].toFixed(2)}${segments.length ? ` ${segments.join(' ')}` : ''}`
  return close ? `${d} Z` : d
}

/** SVG path `d` for a geometry: M/L per ring, Z closing Polygon/MultiPolygon
 *  rings. Points (and MultiPoints) produce '' — they render as circles, not
 *  paths, in the marker layer. */
export function geometryPath(geometry: GeoJSONGeometry | null | undefined, project: Projector): string {
  if (!geometry) return ''
  switch (geometry.type) {
    case 'Point':
    case 'MultiPoint':
      return ''
    case 'LineString':
      return ringPath(geometry.coordinates, project, false)
    case 'MultiLineString': {
      const lines = geometry.coordinates
      if (!Array.isArray(lines)) return ''
      return lines.map((line) => ringPath(line, project, false)).filter(Boolean).join(' ')
    }
    case 'Polygon': {
      const rings = geometry.coordinates
      if (!Array.isArray(rings)) return ''
      return rings.map((ring) => ringPath(ring, project, true)).filter(Boolean).join(' ')
    }
    case 'MultiPolygon': {
      const polys = geometry.coordinates
      if (!Array.isArray(polys)) return ''
      return polys
        .map((poly) => (Array.isArray(poly) ? poly.map((ring) => ringPath(ring, project, true)).filter(Boolean).join(' ') : ''))
        .filter(Boolean)
        .join(' ')
    }
    default:
      return ''
  }
}
