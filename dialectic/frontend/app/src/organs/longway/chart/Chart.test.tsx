import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FeatureCollection } from 'geojson'
import type { MapOptions, StyleSpecification } from 'maplibre-gl'
import type { ChartProps, Vehicle } from '../types'
import { projection as data } from './fixtures/projection'

const mock = vi.hoisted(() => {
  const frames: FrameRequestCallback[] = []
  const maps: Map[] = [], markers: Marker[] = []
  class Map {
    options: MapOptions
    style: StyleSpecification
    sources: Record<string, FeatureCollection> = {}
    filters: Record<string, unknown> = {}
    layout: Record<string, Record<string, unknown>> = {}
    paint: Record<string, Record<string, unknown>> = {}
    events: Record<string, ((e: { point: [number, number] }) => void)[]> = {}
    center = { lng: 45, lat: 22 }
    zoom = 1.5
    hits: { properties: { slug: string; i: number } }[] = []
    canvas = document.createElement('canvas')
    touchZoomRotate = { disableRotation: vi.fn() }
    keyboard = { disableRotation: vi.fn() }
    fitBounds = vi.fn()
    remove = vi.fn()
    resize = vi.fn()
    addControl = vi.fn()
    constructor(options: MapOptions) {
      this.options = options; this.style = options.style as StyleSpecification
      for (const [id, source] of Object.entries(this.style.sources)) if (source.type === 'geojson') this.sources[id] = source.data as FeatureCollection
      for (const layer of this.style.layers) {
        this.paint[layer.id] = { ...layer.paint }
        this.layout[layer.id] = { ...layer.layout }
      }
      maps.push(this)
    }
    on(event: string, layerOrHandler: string | ((e: { point: [number, number] }) => void), handler?: (e: { point: [number, number] }) => void) {
      const key = typeof layerOrHandler === 'string' ? `${event}:${layerOrHandler}` : event
      ;(this.events[key] ??= []).push(typeof layerOrHandler === 'string' ? handler! : layerOrHandler)
    }
    emit(event: string) { this.events[event]?.forEach(fn => fn({ point: [0, 0] })) }
    getSource(id: string) { return { setData: (data: FeatureCollection) => { this.sources[id] = data } } }
    setFilter(id: string, filter: unknown) { this.filters[id] = filter }
    setLayoutProperty(id: string, key: string, value: unknown) { this.layout[id][key] = value }
    setPaintProperty(id: string, key: string, value: unknown) { this.paint[id][key] = value }
    getCenter() { return this.center }
    getZoom() { return this.zoom }
    easeTo = vi.fn()
    getCanvas() { return this.canvas }
    queryRenderedFeatures = vi.fn(() => this.hits)
  }
  class Marker {
    element: HTMLElement
    at: [number, number] = [0, 0]
    removed = false
    constructor(options: { element: HTMLElement }) { this.element = options.element; markers.push(this) }
    setLngLat(at: [number, number]) { this.at = at; return this }
    addTo(map: Map) {
      (map.options.container as HTMLElement).append(this.element)
      const n = markers.indexOf(this)
      this.element.getBoundingClientRect = () => new DOMRect((n % 8) * 95 + 10, Math.floor(n / 8) * 30 + 10, 85, 18)
      return this
    }
    remove() { this.removed = true; this.element.remove() }
  }
  class LngLatBounds {
    points: [number, number][] = []
    extend(p: [number, number]) { this.points.push(p); return this }
  }
  return { Map, Marker, LngLatBounds, maps, markers, frames }
})
vi.mock('maplibre-gl', () => ({ default: { Map: mock.Map, Marker: mock.Marker, LngLatBounds: mock.LngLatBounds, NavigationControl: class {}, AttributionControl: class {} } }))

import Chart, { LegCard, SeasonStrip } from './Chart'
import { JourneyStrip } from './Cards'

const props = (overrides: Partial<ChartProps> = {}): ChartProps => ({ data, focus: null, selected: null, myth: false, onSelectJourney: vi.fn(), onSelectLeg: vi.fn(), ...overrides })
const live = () => mock.markers.filter(m => !m.removed)
const label = (text: string) => live().find(m => m.element.textContent === text)!
const flushFrames = () => act(() => { mock.frames.splice(0).forEach(fn => fn(0)) })
async function ready(p: ChartProps = props()) {
  const rendered = render(<Chart {...p} />)
  await waitFor(() => expect(mock.maps).toHaveLength(1))
  const map = mock.maps[0]
  act(() => map.emit('load'))
  return { ...rendered, map }
}
// Evaluate the actual generated opacity expressions at a feature, rather than
// only matching a preferred spelling of the focus implementation.
function value(expr: unknown, slug: string, zoom = 7): unknown {
  if (!Array.isArray(expr)) return expr
  if (expr[0] === 'get') return slug
  if (expr[0] === '==') return value(expr[1], slug, zoom) === value(expr[2], slug, zoom)
  if (expr[0] === 'case') return value(expr[1], slug, zoom) ? value(expr[2], slug, zoom) : value(expr[3], slug, zoom)
  if (expr[0] === 'interpolate') return zoom >= 6.5 ? value(expr[6], slug, zoom) : 0
  throw new Error(`Unexpected expression: ${JSON.stringify(expr)}`)
}

beforeEach(() => {
  mock.maps.length = 0; mock.markers.length = 0; mock.frames.length = 0
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ type: 'Topology', objects: { land: { type: 'GeometryCollection', geometries: [] } }, arcs: [] }) }))
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: false, media: query })))
  vi.stubGlobal('ResizeObserver', class { observe = vi.fn(); disconnect = vi.fn() })
  vi.stubGlobal('requestAnimationFrame', (fn: FrameRequestCallback) => { mock.frames.push(fn); return mock.frames.length })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 600))
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(390)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Chart: the real register through MapLibre', () => {
  it('builds every consecutive pair of all 19 journeys and checked stops without inventing ink', async () => {
    const { map } = await ready()
    expect(data.journeys).toHaveLength(19)
    expect(map.sources.segs.features).toHaveLength(data.journeys.reduce((n, j) => n + Math.max(0, (j.route?.length ?? 0) - 1), 0))
    for (const j of data.journeys) {
      const segs = map.sources.segs.features.filter(f => f.properties?.slug === j.slug)
      expect(segs).toHaveLength(Math.max(0, (j.route?.length ?? 0) - 1))
      segs.forEach((f, i) => {
        expect(f.properties).toEqual({ slug: j.slug, i, ink: j.segments[i].ink })
        expect(f.geometry).toEqual({ type: 'LineString', coordinates: j.route.slice(i, i + 2).map(p => [p[1], p[0]]) })
      })
      map.sources.stops.features.filter(f => f.properties?.slug === j.slug).forEach((f, i) => {
        expect(f.properties?.checked).toBe([j.segments[i - 1], j.segments[i]].some(s => s && ['dashed', 'contradicted'].includes(s.ink)))
      })
    }
    const inks = (slug: string) => map.sources.segs.features.filter(f => f.properties?.slug === slug).map(f => f.properties?.ink)
    expect(inks('ogasawara')).toEqual(['dashed', 'pencil'])
    expect(inks('banda-islands')[0]).toBe('dashed')
    expect(inks('eritrea-asmara-massawa')).toContain('dotted')
    expect(new Set(inks('lake-tanganyika-liemba'))).toEqual(new Set(['pencil']))
  })

  it('ports the globe, inks, casing, graticule, imagery fade, palette and disabled rotation', async () => {
    const { map } = await ready()
    expect(map.style.projection).toEqual({ type: 'globe' })
    expect(map.options).toMatchObject({ dragRotate: false, pitchWithRotate: false, touchPitch: false })
    expect(map.touchZoomRotate.disableRotation).toHaveBeenCalledOnce()
    expect(map.keyboard.disableRotation).toHaveBeenCalledOnce()
    expect(map.paint['pencil-a']).toMatchObject({ 'line-width': 1.4, 'line-translate': [0.6, 0.5], 'line-opacity': 0.9 })
    expect(map.paint['pencil-b']).toMatchObject({ 'line-width': 1, 'line-translate': [-0.6, -0.6], 'line-opacity': 0.6 })
    expect(map.paint.dotted['line-dasharray']).toEqual([0.1, 2])
    expect(map.paint.dashed['line-dasharray']).toEqual([2.5, 1.5])
    expect(map.paint.contradicted).toMatchObject({ 'line-color': '#c0392b', 'line-dasharray': [1, 1] })
    expect(map.paint.heavy['line-width']).toBe(4.5)
    expect(map.paint.halo).toMatchObject({ 'line-width': 13, 'line-blur': 4, 'line-opacity': 0.28 })
    expect(map.paint.casing['line-opacity']).toEqual(['interpolate', ['linear'], ['zoom'], 4.5, 0, 6.5, 0.85])
    expect(map.paint.imagery['raster-opacity']).toEqual(['interpolate', ['linear'], ['zoom'], 4.5, 0, 6.5, 1])
    expect(map.style.layers.find(l => l.id === 'imagery')?.minzoom).toBe(4.5)
    expect(map.style.sources.imagery).toMatchObject({ tiles: [expect.stringContaining('World_Imagery/MapServer/tile/{z}/{y}/{x}')] })
    expect(map.sources.grat).toMatchObject({ geometry: { type: 'MultiLineString', coordinates: expect.any(Array) } })
    const order = map.style.layers.map(l => l.id)
    expect(order.indexOf('casing')).toBeGreaterThan(order.indexOf('imagery'))
    expect(order.indexOf('pencil-a')).toBeGreaterThan(order.indexOf('casing'))
  })

  it('composes myth, selected halo and focus across every journey layer, then restores them', async () => {
    const p = props(), { map, rerender } = await ready(p)
    const full = structuredClone(map.paint)
    rerender(<Chart {...p} focus="ogasawara" selected="ogasawara" myth />)
    const checked = ['in', ['get', 'ink'], ['literal', ['dashed', 'contradicted']]]
    for (const id of ['pencil-a', 'pencil-b', 'dotted']) expect(map.layout[id].visibility).toBe('none')
    expect(map.filters.casing).toEqual(checked); expect(map.filters.hit).toEqual(checked)
    expect(map.filters.stops).toEqual(['==', ['get', 'checked'], true])
    expect(map.filters.halo).toEqual(['all', ['==', ['get', 'slug'], 'ogasawara'], checked])
    for (const layer of map.style.layers) {
      if (!('source' in layer) || !['segs', 'stops', 'vessels'].includes(layer.source)) continue
      const keys = layer.type === 'circle' ? ['circle-opacity', 'circle-stroke-opacity'] : ['line-opacity']
      for (const key of keys) for (const j of data.journeys) {
        const baseline = Number(value(full[layer.id][key] ?? 1, j.slug))
        expect(value(map.paint[layer.id][key], j.slug)).toBeCloseTo(baseline * (j.slug === 'ogasawara' ? 1 : 0.25))
      }
    }
    expect(live().filter(m => m.element.className === 'jl').every(m => m.element.hidden)).toBe(true)
    expect(live().filter(m => m.element.className === 'sl')).toHaveLength(3)
    rerender(<Chart {...p} />)
    expect(mock.maps).toHaveLength(1)
    expect(map.filters.casing).toBeNull(); expect(map.filters.stops).toBeNull()
    expect(map.layout.dotted.visibility).toBe('visible')
    expect(map.paint.dashed['line-opacity']).toBe(1)
  })

  it('uses fix coordinates and age labels, lists never-heard vessels, and refreshes without moving the camera', async () => {
    const vehicle = data.vehicles[0]
    const vehicles: Vehicle[] = [98, 120, 2880].map((age_min, i) => ({ ...vehicle, name: ['Tanger Express', 'Hours', 'Days'][i], heard: true, fix: { lat: 36, lon: -5, at: '2026-10-28T10:00:00Z', age_min, source: 'ais' } }))
    vehicles.push({ ...vehicle, name: 'Silent', heard: false, fix: null })
    const p = props({ data: { ...data, vehicles, fixes_state: { stale: true, written: '2026-10-28T08:00:00Z', why: 'listener silent' } } })
    const { map, rerender } = await ready(p)
    expect(map.sources.vessels.features).toHaveLength(3)
    expect(map.sources.vessels.features[0]).toMatchObject({ properties: { label: 'Tanger Express, heard 98 min ago', age_min: 98 }, geometry: { coordinates: [-5, 36] } })
    expect(label('Tanger Express, heard 98 min ago').at).toEqual([-5, 36])
    expect(label('Hours, heard 2 h ago')).toBeDefined(); expect(label('Days, heard 2 days ago')).toBeDefined()
    expect(screen.getByText('Silent, never heard')).toBeInTheDocument()
    expect(screen.getByText('1 vehicle never heard').tagName).toBe('SUMMARY')
    expect(screen.getByText('Listener silent since 2026-10-28T08:00:00Z')).toBeInTheDocument()
    expect(live().some(m => m.element.textContent === 'Silent')).toBe(false)
    rerender(<Chart {...p} data={{ ...p.data, vehicles: [] }} />)
    expect(map.sources.vessels.features).toEqual([])
    expect(live().some(m => m.element.className === 'vl')).toBe(false)
    expect(map.fitBounds).not.toHaveBeenCalled()
  })

  it('hides far-side, overlapping, off-map and unfocused labels; selected stops obey myth and facing', async () => {
    const p = props(), { map, rerender } = await ready(p)
    const j = data.journeys.find(j => j.slug === 'ogasawara')!, marker = label(j.title)
    expect(marker.element.tagName).toBe('BUTTON')
    map.center = { lng: marker.at[0], lat: marker.at[1] }
    marker.element.getBoundingClientRect = () => new DOMRect(20, 500, 80, 20)
    act(() => map.emit('move')); flushFrames()
    expect(marker.element.hidden).toBe(false)
    map.center = { lng: marker.at[0] + 180, lat: -marker.at[1] }
    act(() => map.emit('move')); flushFrames()
    expect(marker.element.hidden).toBe(true)
    map.center = { lng: marker.at[0], lat: marker.at[1] }
    marker.element.getBoundingClientRect = () => new DOMRect(-10, 500, 80, 20)
    act(() => map.emit('move')); flushFrames()
    expect(marker.element.hidden).toBe(true)
    for (const m of live()) { m.at[0] = map.center.lng; m.at[1] = map.center.lat; m.element.getBoundingClientRect = () => new DOMRect(20, 50, 80, 20) }
    act(() => map.emit('move')); flushFrames()
    expect(live().filter(m => !m.element.hidden)).toHaveLength(1)
    rerender(<Chart {...p} focus="ogasawara" />)
    expect(live().filter(m => !m.element.hidden).map(m => m.element.textContent)).toEqual([j.title])
    rerender(<Chart {...p} selected="banda-islands" myth />)
    const stopMarkers = live().filter(m => m.element.className === 'sl')
    map.center = { lng: 129, lat: -4 }
    act(() => map.emit('move')); flushFrames()
    expect(stopMarkers.filter(m => !m.element.hidden).map(m => m.element.textContent)).toEqual(['Ambon', 'Banda Neira'])
    map.center = { lng: -51, lat: 4 }
    act(() => map.emit('move')); flushFrames()
    expect(stopMarkers.every(m => m.element.hidden)).toBe(true)
  })

  it('selects from keyboard buttons and hit features, clears on background, fits with reduced motion and cleans up', async () => {
    const p = props({ reducedMotion: true }), { map, unmount, rerender } = await ready(p)
    const j = data.journeys.find(j => j.slug === 'ogasawara')!
    fireEvent.click(label(j.title).element)
    expect(p.onSelectJourney).toHaveBeenCalledWith('ogasawara')
    expect(map.fitBounds).toHaveBeenLastCalledWith(expect.objectContaining({ points: j.route.map(p => [p[1], p[0]]) }), { padding: { top: 40, bottom: 40, left: 40, right: 110 }, maxZoom: 9, duration: 0 })
    map.hits = [{ properties: { slug: 'ogasawara', i: 0 } }]
    act(() => map.emit('click'))
    expect(map.queryRenderedFeatures).toHaveBeenLastCalledWith([0, 0], { layers: ['hit'] })
    expect(p.onSelectLeg).toHaveBeenCalledWith('ogasawara', 0)
    map.hits = []; act(() => map.emit('click'))
    expect(p.onSelectJourney).toHaveBeenLastCalledWith(null)
    // Letting go of a journey returns to the whole globe the map opened on, not the last route's zoom.
    expect(map.easeTo).not.toHaveBeenCalled()
    rerender(<Chart {...p} selected={null} />)
    expect(map.easeTo).toHaveBeenCalledWith({ center: { lng: 45, lat: 22 }, zoom: 1.5, duration: 0 })
    unmount()
    expect(map.remove).toHaveBeenCalledOnce()
    expect(live()).toHaveLength(0)
  })

  it('honours system reduced motion and survives StrictMode without duplicate maps', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduced-motion') }))
    const p = props({ selected: 'ogasawara', reducedMotion: false })
    const { unmount } = render(<StrictMode><Chart {...p} /></StrictMode>)
    await waitFor(() => expect(mock.maps).toHaveLength(1))
    act(() => mock.maps[0].emit('load'))
    expect(mock.maps[0].fitBounds).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ duration: 0 }))
    expect(vi.mocked(fetch).mock.calls.length).toBeLessThanOrEqual(1)
    unmount()
  })
})

describe('Cards outside the chart', () => {
  it('renders twelve hatched estimate cells, the key and note; sourced seasons expose evidence', () => {
    const { container, rerender } = render(<SeasonStrip season={{ good: [9, 10], possible: [8], avoid: [1], basis: 'hypothesis', note: 'Weather estimate.' }} sources={{}} />)
    expect(container.querySelectorAll('.months.est .m')).toHaveLength(12)
    expect(screen.getByText(/An estimate, not checked\./)).toHaveTextContent('Weather estimate.')
    expect(screen.getByText(/Hatched: an estimate/)).toBeInTheDocument()
    rerender(<SeasonStrip season={{ good: [10], possible: [], avoid: [], basis: ['S1', 'S3', 'S4'] }} sources={data.sources.ogasawara} />)
    expect(container.querySelector('.est')).toBeNull()
    expect(screen.getByText('From S1, S3, S4.')).toBeInTheDocument()
    expect(screen.getByText('Evidence S1, S3, S4')).toBeInTheDocument()
    expect(screen.getAllByText(/checked 9 Oct 2026/)).toHaveLength(3)
  })

  it('renders the real leg, claim, checked date, publisher, scope, Source and faded rule; discussion is keyboard accessible', () => {
    const j = data.journeys.find(j => j.slug === 'ogasawara')!, onDiscuss = vi.fn()
    const sources = { ...data.sources.ogasawara, S1: { ...data.sources.ogasawara.S1, faded: true } }
    const { container } = render(<LegCard journey={j} index={0} sources={sources} onDiscuss={onDiscuss} />)
    expect(screen.getByRole('article')).toHaveAttribute('tabindex', '0')
    expect(screen.getByText(`${j.segments[0].from} to ${j.segments[0].to}`)).toBeInTheDocument()
    expect(screen.getByText(/Dates, tickets and quality are not confirmed/)).toBeInTheDocument()
    expect(container.querySelector('.ev')).toHaveTextContent(sources.S1.claim)
    expect(container.querySelector('.faded')).toHaveTextContent('past its recheck rule')
    expect(container.querySelector('.ev')).toHaveTextContent('checked 9 Oct 2026; Ogasawara Kaiun')
    expect(container.querySelector('.ev')).toHaveTextContent(sources.S1.scope!)
    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute('href', sources.S1.url)
    fireEvent.click(screen.getByRole('button', { name: 'Discuss this leg' }))
    expect(onDiscuss).toHaveBeenCalledWith('ogasawara', 0)
  })

  it('preserves unchecked and contradicted status text and the two pencil strokes in strips', () => {
    const j = data.journeys.find(j => j.slug === 'ogasawara')!
    const { rerender, container } = render(<LegCard journey={j} index={0} sources={{ S1: { ...data.sources.ogasawara.S1, status: 'unverified', url: 'javascript:alert(1)' } }} />)
    expect(screen.getByText(/not yet checked/)).toBeInTheDocument(); expect(screen.queryByRole('link')).toBeNull()
    rerender(<LegCard journey={j} index={0} sources={{ S1: { ...data.sources.ogasawara.S1, status: 'contradicted' } }} />)
    expect(container.querySelector('.ev')).toHaveTextContent('(contradicted;')
    const pencil = data.journeys.find(j => j.slug === 'lake-tanganyika-liemba')!
    rerender(<JourneyStrip journey={pencil} />)
    expect(container.querySelectorAll('.ink-pencil line')).toHaveLength(pencil.segments.length * 2)
  })
})
