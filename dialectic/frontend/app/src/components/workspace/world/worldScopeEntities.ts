import * as Cesium from 'cesium'
import type { GeoScope } from '../../../types/geo.ts'
import { isProvisional } from './worldScopes.ts'

const FILL = Cesium.Color.fromCssColorString('#F2A24A').withAlpha(0.18)
const LINE = Cesium.Color.fromCssColorString('#F2A24A')
const PROVISIONAL = Cesium.Color.fromCssColorString('#A38865')
const PIN = Cesium.Color.fromCssColorString('#54D8C6')

/** Add one durable scope as its one real Cesium entity, including selection. */
export function addScope(
  viewer: Cesium.Viewer, scope: GeoScope, selected = false,
): void {
  const provisional = isProvisional(scope)
  const line = provisional ? PROVISIONAL : LINE
  const g = scope.geometry
  const base = {
    id: scope.id,
    name: scope.label || scope.kind,
    description: undefined,
    properties: { worldScope: true, selected },
  }
  if (g.type === 'Point') {
    const [lon, lat] = g.coordinates as number[]
    viewer.entities.add({
      ...base,
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: selected ? 14 : 9,
        color: provisional ? PROVISIONAL : PIN,
        outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
        outlineWidth: selected ? 3 : 1,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: scope.label,
        font: '12px sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#E3D2B4'),
        pixelOffset: new Cesium.Cartesian2(0, -16),
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString('#150D07').withAlpha(0.8),
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
        width: selected ? 5 : provisional ? 2 : 3,
        material: provisional
          ? new Cesium.PolylineDashMaterialProperty({ color: line, dashLength: 12 })
          : line,
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
        material: provisional ? PROVISIONAL.withAlpha(0.08) : FILL,
        outline: true,
        outlineColor: line,
        outlineWidth: selected ? 4 : 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: selected ? 4 : provisional ? 1.5 : 2,
        material: provisional
          ? new Cesium.PolylineDashMaterialProperty({ color: line, dashLength: 10 })
          : line,
        clampToGround: true,
      },
    })
  }
}
