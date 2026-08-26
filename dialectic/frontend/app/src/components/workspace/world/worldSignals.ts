import * as Cesium from 'cesium'
import type { WorldSignal } from '../../../types/geo.ts'

/**
 * Contact glyphs — one look per layer, the way God's Eye View reads a scene
 * at a glance: an aircraft is an arrow pointing where it is going, a quake is
 * a ring sized by magnitude, a fire burns, the ISS carries its orbit.
 *
 * A SIGNAL IS STILL NOT AUTHORITY. These entities are pickable so a person
 * can TRACK one (a presentation act — the camera follows, the card opens),
 * and that is all picking does. Durable geography still requires the explicit
 * placement action in the text list, which is a server write by a human. The
 * `worldSignal` property is what keeps the two apart at the pick handler.
 */

const LAYER_COLORS: Record<string, string> = {
  aircraft: '#56B7F2',
  earthquakes: '#F2A93B',
  fires: '#FF5A36',
  satellites: '#B98CF5',
  launches: '#57E2A5',
}
const DEFAULT_COLOR = '#56B7F2'

function colorFor(signal: WorldSignal): Cesium.Color {
  return Cesium.Color.fromCssColorString(LAYER_COLORS[signal.layer] ?? DEFAULT_COLOR)
}

function num(value: unknown): number | null {
  const parsed = typeof value === 'string' ? Number(value) : value
  return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null
}

/** Metres above the ellipsoid this contact should be drawn at, or null for
 *  clamp-to-ground. Altitude is evidence too: an airliner at FL370 must not
 *  sit on the terrain under it. */
export function signalHeight(signal: WorldSignal): number | null {
  const feet = num(signal.details.altitude_ft)
  if (feet !== null) return feet * 0.3048
  const km = num(signal.details.altitude_km)
  if (km !== null) return km * 1000
  return null
}

/** A triangle pointing along the contact's track — Cesium has no arrow glyph,
 *  so this is one drawn as a canvas the billboard rotates. */
function arrowCanvas(color: Cesium.Color): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = 32
  canvas.height = 32
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas
  ctx.beginPath()
  ctx.moveTo(16, 2)
  ctx.lineTo(28, 30)
  ctx.lineTo(16, 22)
  ctx.lineTo(4, 30)
  ctx.closePath()
  ctx.fillStyle = color.toCssColorString()
  ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.85)'
  ctx.lineWidth = 1.5
  ctx.stroke()
  return canvas
}

const arrowCache = new Map<string, HTMLCanvasElement>()
function arrowFor(color: Cesium.Color): HTMLCanvasElement {
  const key = color.toCssColorString()
  const cached = arrowCache.get(key)
  if (cached) return cached
  const canvas = arrowCanvas(color)
  arrowCache.set(key, canvas)
  return canvas
}

function labelOf(signal: WorldSignal, color: Cesium.Color, selected: boolean) {
  return {
    text: signal.label,
    font: selected ? 'bold 12px monospace' : '11px monospace',
    fillColor: color.brighten(0.5, new Cesium.Color()),
    pixelOffset: new Cesium.Cartesian2(0, -20),
    showBackground: true,
    backgroundColor: Cesium.Color.fromCssColorString('#07141B').withAlpha(0.82),
    distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 3_000_000),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
  }
}

/** Add one server-held observation with the glyph its layer deserves. */
export function addSignal(
  viewer: Cesium.Viewer, signal: WorldSignal, selected = false,
): void {
  const g = signal.geometry
  const color = colorFor(signal)
  const base = {
    id: signal.id,
    name: signal.label || signal.layer,
    properties: { worldSignal: true, layer: signal.layer },
  }

  if (g.type === 'Point') {
    const [lon, lat] = g.coordinates as number[]
    const height = signalHeight(signal)
    const position = height === null
      ? Cesium.Cartesian3.fromDegrees(lon, lat)
      : Cesium.Cartesian3.fromDegrees(lon, lat, height)
    const track = num(signal.details.track_deg)

    if (signal.layer === 'aircraft' && track !== null) {
      viewer.entities.add({
        ...base,
        position,
        billboard: {
          image: arrowFor(color),
          width: selected ? 26 : 18,
          height: selected ? 26 : 18,
          rotation: Cesium.Math.toRadians(-track),
          alignedAxis: Cesium.Cartesian3.ZERO,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: labelOf(signal, color, selected),
        // The leader line is what makes an airborne contact readable: the
        // glyph is where the aircraft IS, the line says where it is OVER.
        polyline: height === null ? undefined : {
          positions: [Cesium.Cartesian3.fromDegrees(lon, lat), position],
          width: 1,
          material: color.withAlpha(0.35),
        },
      })
      return
    }

    // A quake's ring is its magnitude; everything else is a point.
    const magnitude = num(signal.details.magnitude)
    if (signal.layer === 'earthquakes' && magnitude !== null) {
      viewer.entities.add({
        ...base,
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        ellipse: {
          semiMajorAxis: Math.pow(10, magnitude / 2) * 900,
          semiMinorAxis: Math.pow(10, magnitude / 2) * 900,
          material: color.withAlpha(selected ? 0.34 : 0.18),
          outline: true,
          outlineColor: color,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        },
        point: {
          pixelSize: selected ? 14 : 9,
          color: color.withAlpha(0.9),
          outlineColor: Cesium.Color.WHITE.withAlpha(0.8),
          outlineWidth: 1,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: labelOf(signal, color, selected),
      })
      return
    }

    viewer.entities.add({
      ...base,
      position,
      point: {
        pixelSize: selected ? 17 : 12,
        color: color.withAlpha(0.85),
        outlineColor: Cesium.Color.WHITE.withAlpha(selected ? 1 : 0.8),
        outlineWidth: selected ? 2 : 1,
        heightReference: height === null
          ? Cesium.HeightReference.CLAMP_TO_GROUND
          : Cesium.HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: labelOf(signal, color, selected),
    })
    return
  }

  if (g.type === 'LineString') {
    const flat = (g.coordinates as number[][]).flatMap(([lon, lat]) => [lon, lat])
    viewer.entities.add({
      ...base,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: 3,
        material: new Cesium.PolylineDashMaterialProperty({ color, dashLength: 8 }),
        clampToGround: true,
      },
    })
    return
  }

  if (g.type === 'Polygon') {
    const outer = (g.coordinates as number[][][])[0] ?? []
    const flat = outer.flatMap(([lon, lat]) => [lon, lat])
    viewer.entities.add({
      ...base,
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(flat)),
        material: color.withAlpha(0.14),
        outline: true,
        outlineColor: color,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: 2,
        material: new Cesium.PolylineDashMaterialProperty({ color, dashLength: 8 }),
        clampToGround: true,
      },
    })
  }
}

/** The fading breadcrumb behind a tracked contact. Positions are the fixes we
 *  actually received — never interpolated, so the trail is evidence and not a
 *  drawing of one. */
export function addTrail(
  viewer: Cesium.Viewer, signal: WorldSignal, positions: Cesium.Cartesian3[],
): void {
  if (positions.length < 2) return
  viewer.entities.add({
    id: `${signal.id}:trail`,
    properties: { worldSignalTrail: true },
    polyline: {
      positions,
      width: 2,
      material: new Cesium.PolylineGlowMaterialProperty({
        color: colorFor(signal).withAlpha(0.75),
        glowPower: 0.25,
      }),
    },
  })
}
