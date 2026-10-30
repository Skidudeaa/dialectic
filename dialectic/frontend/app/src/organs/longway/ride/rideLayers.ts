import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import type { GeoJSONSource, Map as RideMap, StyleSpecification } from 'maplibre-gl'
import type { RideData, RideLeg } from '../types'

export const VIEW = '#ff2fd6'
const line = (pts: number[][], properties = {}): Feature<LineString> => ({ type: 'Feature', properties, geometry: { type: 'LineString', coordinates: pts } })
const lines = (features: Feature<LineString>[]): FeatureCollection<LineString> => ({ type: 'FeatureCollection', features: features.filter(f => f.geometry.coordinates.length >= 2) })
const lngLat = (p: number[]) => [p[1], p[0]]
export function summitWindows(leg: RideLeg) {
  const peaks = new Map<string, typeof leg.sights.sights[number]>()
  for (const w of leg.sights.sights) if (w.kind === 'peak' && (w.major || w.covered || (w.size ?? 0) >= 1.2) && w.to) {
    const old = peaks.get(w.name)
    if (!old || (w.size ?? 0) > (old.size ?? 0)) peaks.set(w.name, w)
  }
  return [...peaks.values()]
}
export function rideStyle(leg: RideLeg): StyleSpecification {
  const peaks = summitWindows(leg)
  const summitData: FeatureCollection<Point> = { type: 'FeatureCollection', features: peaks.map(w => ({ type: 'Feature', properties: { name: w.name }, geometry: { type: 'Point', coordinates: lngLat(w.to!) } })) }
  return {
    version: 8,
    sources: {
      imagery: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 19, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics' },
      track: { type: 'geojson', data: lines([line(leg.sights.km.map(r => [r[4], r[3]]))]) },
      // MapLibre simplifies the source before applying pixel-space line-offset.
      teeth: { type: 'geojson', tolerance: 2, data: lines((['left', 'right'] as const).flatMap(side => leg.sights[side].filter(s => s.c >= 2).map(s => line(s.pts.map(lngLat), { side, c: s.c })))) },
      summits: { type: 'geojson', data: summitData },
      sightlines: { type: 'geojson', data: lines(leg.sights.sights.filter(w => w.kind === 'peak' && (w.major || w.covered || (w.size ?? 0) >= 1.2) && w.to).map(w => line([lngLat(w.best), lngLat(w.to!)]))) },
      signal: { type: 'geojson', data: lines((leg.coverage?.segments ?? []).map(s => line(s.pts.map(lngLat), { color: leg.coverage!.classes[s.c]?.color ?? '#999' }))) },
      measured: { type: 'geojson', data: lines((leg.coverage?.measured ?? []).map(pts => line(pts.map(lngLat)))) },
      observed: { type: 'geojson', data: lines([]) },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#dce7e8' } },
      { id: 'imagery', source: 'imagery', type: 'raster' },
      { id: 'track', source: 'track', type: 'line', paint: { 'line-color': '#fff', 'line-width': 2, 'line-opacity': .7 } },
      { id: 'signal', source: 'signal', type: 'line', layout: { visibility: 'none' }, paint: { 'line-color': ['get', 'color'], 'line-width': 6 } },
      { id: 'measured', source: 'measured', type: 'line', layout: { visibility: 'none' }, paint: { 'line-color': '#fff', 'line-width': 1.5 } },
      ...([2, 3] as const).flatMap(c => (['left', 'right'] as const).map(side => {
        const width = c === 3 ? 14 : 7
        return { id: `teeth-${side}-${c}`, source: 'teeth', type: 'line' as const,
          filter: ['all', ['==', ['get', 'c'], c], ['==', ['get', 'side'], side]] as import('maplibre-gl').ExpressionSpecification,
          layout: { 'line-cap': 'butt' as const, 'line-join': 'round' as const },
          paint: { 'line-color': VIEW, 'line-width': width, 'line-offset': (side === 'left' ? -1 : 1) * (5 + width / 2), 'line-dasharray': [2 / width, 4 / width], 'line-opacity': c === 3 ? .95 : .7 },
        }
      })),
      { id: 'sightlines', source: 'sightlines', type: 'line', paint: { 'line-color': VIEW, 'line-width': 1, 'line-dasharray': [3, 5], 'line-opacity': .7 } },
      { id: 'summits', source: 'summits', type: 'symbol', layout: { 'icon-image': 'summit', 'icon-allow-overlap': true } },
      { id: 'observed', source: 'observed', type: 'line', paint: { 'line-color': '#fff', 'line-width': 3, 'line-dasharray': [2, 2] } },
    ],
  }
}
export function addSummitIcon(map: RideMap) {
  const width = 20, data = new Uint8Array(width * width * 4)
  for (let y = 2; y < 18; y++) for (let x = 0; x < width; x++) {
    if (Math.abs(x - 9.5) <= (y - 2) / 2) {
      const i = (y * width + x) * 4
      data[i] = 255; data[i + 1] = 255; data[i + 2] = 255; data[i + 3] = 255
    }
  }
  map.addImage('summit', { width, height: width, data })
}
export function updateStoredTrack(map: RideMap, track: RideData['track'], until: number) {
  // A replay never draws observations that had not happened yet.
  const pts = track.filter(p => Date.parse(p[0]) <= until).map(p => [p[2], p[1]])
  ;(map.getSource('observed') as GeoJSONSource).setData(lines([line(pts)]))
}
