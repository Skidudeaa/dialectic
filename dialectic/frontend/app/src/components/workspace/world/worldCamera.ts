// The `view` axis grammar for Atlas / World (World Lens, 2026-08-25).
//
// WHY a pure module: the router treats `view` as opaque (workspaceRoute.ts)
// and only THIS file knows what a world view means, so the grammar is
// provable without Cesium or a mounted hook. Same reasoning that put the
// room grammar in lib/workspaceRoute.ts.
//
// Grammar:  world[:lat,lon,alt,heading,pitch][;room=<uuid>]
//   - `world` alone = World mode, framing every scope the viewer can see.
//   - the five numbers restore a camera (degrees, metres, degrees, degrees),
//     4 decimals of latitude/longitude (~11 m), whole metres, whole degrees —
//     GEV's share-link precision, which is enough to reopen the same view and
//     short enough to live in a URL.
//   - `room=` prefocuses one room's scopes (the Bench's "World ↗" entry).
//
// Anything undecodable is `null`: the scene's default, never an error.

export interface WorldCamera {
  lat: number
  lon: number
  alt: number
  heading: number
  pitch: number
}

export interface WorldViewState {
  camera: WorldCamera | null
  roomId: string | null
}

export const WORLD_VIEW_PREFIX = 'world'

export function isWorldView(view: string | null | undefined): boolean {
  return typeof view === 'string' && (view === WORLD_VIEW_PREFIX || view.startsWith(`${WORLD_VIEW_PREFIX}:`) || view.startsWith(`${WORLD_VIEW_PREFIX};`))
}

function finite(value: string): number | null {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function decodeWorldView(view: string | null | undefined): WorldViewState | null {
  if (!isWorldView(view)) return null
  const body = (view as string).slice(WORLD_VIEW_PREFIX.length)
  const [cameraPart, ...opts] = body.split(';')
  let camera: WorldCamera | null = null
  if (cameraPart.startsWith(':')) {
    const parts = cameraPart.slice(1).split(',')
    if (parts.length === 5) {
      const nums = parts.map(finite)
      if (nums.every((n) => n !== null)) {
        const [lat, lon, alt, heading, pitch] = nums as number[]
        if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && alt > 0) {
          camera = { lat, lon, alt, heading, pitch }
        }
      }
    }
  }
  let roomId: string | null = null
  for (const opt of opts) {
    const [key, value] = opt.split('=')
    if (key === 'room' && value) roomId = value
  }
  return { camera, roomId }
}

export function encodeWorldView(state: WorldViewState): string {
  let out = WORLD_VIEW_PREFIX
  if (state.camera) {
    const c = state.camera
    out += `:${c.lat.toFixed(4)},${c.lon.toFixed(4)},${Math.round(c.alt)},${Math.round(c.heading)},${Math.round(c.pitch)}`
  }
  if (state.roomId) out += `;room=${state.roomId}`
  return out
}
