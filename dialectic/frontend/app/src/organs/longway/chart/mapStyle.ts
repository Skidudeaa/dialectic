import type { Feature, FeatureCollection, LineString, MultiLineString, Point } from 'geojson'
import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl'
import type { ChartProps, Ink, Journey, RoutePoint, Vehicle } from '../types'

export const checked = (ink: Ink) => ink === 'dashed' || ink === 'contradicted'
export const point = (p: RoutePoint): [number, number] => [p[1], p[0]]
export const CHECKED: ExpressionSpecification = ['in', ['get', 'ink'], ['literal', ['dashed', 'contradicted']]]
export const byInk = (ink: Ink): ExpressionSpecification => ['==', ['get', 'ink'], ink]
export const fadeIn = (to: number | ExpressionSpecification): ExpressionSpecification => ['interpolate', ['linear'], ['zoom'], 4.5, 0, 6.5, to]
export const opacity = (focus: string | null, full = 1): number | ExpressionSpecification => focus
  ? ['case', ['==', ['get', 'slug'], focus], full, full * 0.25] : full

/** A pending Scout proposal on a pencil leg draws it dotted: "a source describes this leg, nobody has checked it"
 *  is exactly what a proposal is. A leg already in ink keeps its ink; a person's confirm is what moves it. */
export const inkWithProposal = (s: { ink: Ink; proposed?: boolean }): Ink => (s.proposed && s.ink === 'pencil' ? 'dotted' : s.ink)

export function segments(journeys: Journey[]): FeatureCollection<LineString> {
  return { type: 'FeatureCollection', features: journeys.flatMap(j => j.segments.map((s, i) => ({
    type: 'Feature' as const, properties: { slug: j.slug, i, ink: inkWithProposal(s) },
    geometry: { type: 'LineString' as const, coordinates: [point(j.route[i]), point(j.route[i + 1])] },
  }))) }
}
export const stopChecked = (j: Journey, k: number) => [j.segments[k - 1], j.segments[k]].some(s => s && checked(s.ink))
// The raw register includes a shared trip with route:null and no segments.
// Keep that record in the projection, without inventing map geometry.
export function stops(journeys: Journey[]): FeatureCollection<Point> {
  return { type: 'FeatureCollection', features: journeys.flatMap(j => (j.route ?? []).map((p, k) => ({
    type: 'Feature' as const, properties: { slug: j.slug, checked: stopChecked(j, k) },
    geometry: { type: 'Point' as const, coordinates: point(p) },
  }))) }
}
export function age(minutes: number) {
  if (minutes < 120) return `${Math.floor(minutes)} min ago`
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h ago`
  return `${Math.floor(minutes / 1440)} days ago`
}
export const vesselLabel = (v: Vehicle) => `${v.name}, heard ${age(v.fix!.age_min)}`
export function vessels(vehicles: Vehicle[]): FeatureCollection<Point> {
  return { type: 'FeatureCollection', features: vehicles.flatMap(v => v.fix && v.heard ? [{
    type: 'Feature' as const, properties: { slug: v.journey, name: v.name, age_min: v.fix.age_min, at: v.fix.at, label: vesselLabel(v) },
    geometry: { type: 'Point' as const, coordinates: [v.fix.lon, v.fix.lat] },
  }] : []) }
}
export function graticule(): Feature<MultiLineString> {
  const lines: number[][][] = []
  for (let lon = -180; lon < 180; lon += 30) lines.push(Array.from({ length: 81 }, (_, k) => [lon, -80 + 2 * k]))
  for (let lat = -60; lat <= 60; lat += 30) lines.push(Array.from({ length: 181 }, (_, k) => [-180 + 2 * k, lat]))
  return { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: lines } }
}

const fallback = { sea: '#dce7e8', land: '#f2ead8', coast: '#b4c3c2', grat: '#cddadb', ink: '#13283a', 'ink-2': '#44586a', pencil: '#7a8790', contra: '#c0392b', panel: '#f7faf9', good: '#a51f66' }
export function colors(element: HTMLElement) {
  // ponytail: the canvas reads theme tokens once at mount; theme changes need a remount.
  // Missing shell tokens use globe.html's original light chart-table palette.
  const css = getComputedStyle(element)
  return Object.fromEntries(Object.entries(fallback).map(([key, value]) => [key, css.getPropertyValue(`--${key}`).trim() || value])) as typeof fallback
}
export function style(land: Feature | FeatureCollection, props: ChartProps, c: ReturnType<typeof colors>, dark: boolean): StyleSpecification {
  const { journeys, vehicles } = props.data
  return {
    version: 8, projection: { type: 'globe' },
    sources: {
      land: { type: 'geojson', data: land }, grat: { type: 'geojson', data: graticule() },
      segs: { type: 'geojson', data: segments(journeys) }, stops: { type: 'geojson', data: stops(journeys) },
      vessels: { type: 'geojson', data: vessels(vehicles) },
      imagery: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, maxzoom: 19, attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics' },
    },
    layers: [
      { id: 'sea', type: 'background', paint: { 'background-color': c.sea } },
      { id: 'land', type: 'fill', source: 'land', paint: { 'fill-color': c.land } },
      { id: 'coast', type: 'line', source: 'land', paint: { 'line-color': c.coast, 'line-width': 0.6 } },
      { id: 'grat', type: 'line', source: 'grat', paint: { 'line-color': c.grat, 'line-width': 0.6 } },
      { id: 'imagery', type: 'raster', source: 'imagery', minzoom: 4.5, paint: { 'raster-opacity': fadeIn(1), 'raster-brightness-max': dark ? 0.75 : 1 } },
      { id: 'halo', type: 'line', source: 'segs', filter: ['==', ['get', 'slug'], ''], layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.good, 'line-opacity': 0.28, 'line-width': 13, 'line-blur': 4 } },
      { id: 'casing', type: 'line', source: 'segs', minzoom: 4.5, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.panel, 'line-width': 6, 'line-opacity': fadeIn(0.85) } },
      { id: 'pencil-a', type: 'line', source: 'segs', filter: byInk('pencil'), layout: { 'line-cap': 'round' }, paint: { 'line-color': c.pencil, 'line-width': 1.4, 'line-opacity': 0.9, 'line-translate': [0.6, 0.5] } },
      { id: 'pencil-b', type: 'line', source: 'segs', filter: byInk('pencil'), layout: { 'line-cap': 'round' }, paint: { 'line-color': c.pencil, 'line-width': 1, 'line-opacity': 0.6, 'line-translate': [-0.6, -0.6] } },
      { id: 'dotted', type: 'line', source: 'segs', filter: byInk('dotted'), layout: { 'line-cap': 'round' }, paint: { 'line-color': c['ink-2'], 'line-width': 2.8, 'line-dasharray': [0.1, 2] } },
      { id: 'dashed', type: 'line', source: 'segs', filter: byInk('dashed'), paint: { 'line-color': c.ink, 'line-width': 2.8, 'line-dasharray': [2.5, 1.5] } },
      { id: 'heavy', type: 'line', source: 'segs', filter: byInk('heavy'), paint: { 'line-color': c.ink, 'line-width': 4.5 } },
      { id: 'contradicted', type: 'line', source: 'segs', filter: byInk('contradicted'), paint: { 'line-color': c.contra, 'line-width': 2.4, 'line-dasharray': [1, 1] } },
      { id: 'stops', type: 'circle', source: 'stops', paint: { 'circle-radius': 3, 'circle-color': c.panel, 'circle-stroke-color': c['ink-2'], 'circle-stroke-width': 1.2 } },
      { id: 'hit', type: 'line', source: 'segs', paint: { 'line-color': c.ink, 'line-opacity': 0.01, 'line-width': 18 } },
      { id: 'vessels', type: 'circle', source: 'vessels', paint: { 'circle-radius': 4, 'circle-color': c.ink, 'circle-stroke-color': c.panel, 'circle-stroke-width': 1.5 } },
    ],
  }
}
