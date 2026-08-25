// Pure helpers over GeoScope for the World renderer and its list.
//
// WHY here and not in WorldView: these need no Cesium, so the tests and the
// list-first fallback can use them without loading the globe chunk.
import type { GeoScope } from '../../../types/geo.ts'
import type { AtlasNode } from '../../../types/atlas.ts'
import type { AtlasNavigateDestination } from '../scenes/AtlasScene'

/** Where a tap on a scope lands. The subject decides: a room's own geometry
 *  opens the room; a reading opens that reading in Focus; a mark opens the
 *  mark; a message opens the transcript at it. The object ids REUSE the
 *  workspace-object conventions (types/atlas.ts) — no second id scheme. */
export function scopeDestination(scope: GeoScope): AtlasNavigateDestination & { messageId?: string } {
  const { entity, id } = scope.subject
  switch (entity) {
    case 'reading_items':
      return { roomId: scope.room_id, object: `reading:${id}` }
    case 'field_marks':
      return { roomId: scope.room_id, object: `field_mark:${id}` }
    case 'messages':
      return { roomId: scope.room_id, messageId: id }
    default:
      return { roomId: scope.room_id }
  }
}

/** The node a scope is about, when the projection carries it. */
export function scopeNode(scope: GeoScope, nodesById: Map<string, AtlasNode>): AtlasNode | undefined {
  const { entity, id } = scope.subject
  if (entity === 'rooms') return nodesById.get(`room:${id}`)
  if (entity === 'reading_items') return nodesById.get(`reading:${id}`)
  if (entity === 'field_marks') return nodesById.get(`field_mark:${id}`)
  return undefined
}

/** A provisional (machine-proposed) scope is drawn dashed and dim; the
 *  authority column, not a style, is what makes it so. */
export function isProvisional(scope: GeoScope): boolean {
  return scope.authority === 'machine_proposed'
}

/** Bounding box over every scope's geometry, [west, south, east, north],
 *  or null when there is nothing to frame. */
export function scopesBounds(scopes: GeoScope[]): [number, number, number, number] | null {
  let west = 180, south = 90, east = -180, north = -90
  let any = false
  const visit = (pos: unknown) => {
    if (!Array.isArray(pos) || pos.length < 2) return
    const [lon, lat] = pos as number[]
    if (typeof lon !== 'number' || typeof lat !== 'number') return
    any = true
    west = Math.min(west, lon); east = Math.max(east, lon)
    south = Math.min(south, lat); north = Math.max(north, lat)
  }
  const walk = (coords: unknown) => {
    if (!Array.isArray(coords)) return
    if (coords.length >= 2 && typeof coords[0] === 'number') { visit(coords); return }
    for (const c of coords) walk(c)
  }
  for (const s of scopes) walk(s.geometry.coordinates)
  return any ? [west, south, east, north] : null
}

export const KIND_LABEL: Record<GeoScope['kind'], string> = {
  point: 'Point',
  route: 'Route',
  polygon: 'Area',
  region: 'Region',
}

export const AUTHORITY_LABEL: Record<GeoScope['authority'], string> = {
  human_confirmed: 'confirmed',
  source_reported: 'reported',
  machine_proposed: 'proposed',
}
