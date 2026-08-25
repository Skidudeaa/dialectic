import * as Cesium from 'cesium'
import type { WorldSignal } from '../../../types/geo.ts'

const SIGNAL = Cesium.Color.fromCssColorString('#56B7F2')
const SIGNAL_FILL = SIGNAL.withAlpha(0.14)

/** Add one server-held observation as a non-selectable, blue signal entity. */
export function addSignal(viewer: Cesium.Viewer, signal: WorldSignal): void {
  const g = signal.geometry
  const base = {
    id: signal.id,
    name: signal.label || signal.layer,
    description: undefined,
    properties: { worldSignal: true },
  }
  if (g.type === 'Point') {
    const [lon, lat] = g.coordinates as number[]
    viewer.entities.add({
      ...base,
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: 12,
        color: SIGNAL.withAlpha(0.78),
        outlineColor: Cesium.Color.WHITE.withAlpha(0.8),
        outlineWidth: 1,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: signal.label,
        font: '11px sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#C7E9FA'),
        pixelOffset: new Cesium.Cartesian2(0, -18),
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString('#07141B').withAlpha(0.82),
      },
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
        material: new Cesium.PolylineDashMaterialProperty({ color: SIGNAL, dashLength: 8 }),
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
        material: SIGNAL_FILL,
        outline: true,
        outlineColor: SIGNAL,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: 2,
        material: new Cesium.PolylineDashMaterialProperty({ color: SIGNAL, dashLength: 8 }),
        clampToGround: true,
      },
    })
  }
}
