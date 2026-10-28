import maplibregl from 'maplibre-gl'
import type { GeoJSONSource, Map as Globe } from 'maplibre-gl'
import type { ChartProps, Journey } from '../types'
import { CHECKED, checked, fadeIn, opacity, point, segments, stops, stopChecked, vessels, vesselLabel } from './mapStyle'

type Label = { el: HTMLElement; marker: maplibregl.Marker; at: [number, number]; slug: string; checked: boolean }
const priority: Record<string, number> = { researching: 0, shortlisted: 0, designing: 0, hold: 1 }
const rad = (d: number) => d * Math.PI / 180

export function mountMap(map: Globe, container: HTMLElement, current: () => ChartProps) {
  let loaded = false
  let previous: ChartProps | null = null
  let fitted: string | null = null
  let journeyLabels: Label[] = [], stopLabels: Label[] = [], vesselLabels: Label[] = []
  let frame: number | null = null
  const remove = (labels: Label[]) => labels.forEach(l => l.marker.remove())
  const facing = ([lng, lat]: [number, number]) => {
    const c = map.getCenter()
    return Math.sin(rad(lat)) * Math.sin(rad(c.lat)) + Math.cos(rad(lat)) * Math.cos(rad(c.lat)) * Math.cos(rad(lng - c.lng)) > 0.3
  }
  function placeLabels() {
    const p = current(), box = container.getBoundingClientRect(), placed: DOMRect[] = []
    const labels = [
      ...vesselLabels.map(l => ({ l, show: !p.focus || p.focus === l.slug })),
      ...journeyLabels.map(l => ({ l, show: !p.selected && (!p.focus || p.focus === l.slug) && (!p.myth || l.checked) })),
      ...stopLabels.map(l => ({ l, show: (!p.focus || p.focus === l.slug) && (!p.myth || l.checked) })),
    ]
    for (const { l, show } of labels) {
      l.el.hidden = !show || !facing(l.at)
      if (l.el.hidden) continue
      const r = l.el.getBoundingClientRect()
      const off = r.left < box.left || r.right > box.right || r.top < box.top || r.bottom > box.bottom
      if (off || placed.some(q => r.left < q.right + 4 && r.right > q.left - 4 && r.top < q.bottom + 2 && r.bottom > q.top - 2)) l.el.hidden = true
      else placed.push(r)
    }
  }
  function queueLabels() {
    if (frame !== null) return
    frame = requestAnimationFrame(() => { frame = null; placeLabels() })
  }
  function fit(j: Journey) {
    if (!j.route?.length) return
    const b = new maplibregl.LngLatBounds()
    j.route.forEach(p => b.extend(point(p)))
    const padding = container.clientWidth <= 760 ? { top: 40, bottom: 40, left: 40, right: 110 } : { top: 90, bottom: 90, left: 90, right: 200 }
    // A system preference always wins, even if a caller passes false.
    const reduce = current().reducedMotion || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    map.fitBounds(b, { padding, maxZoom: 9, duration: reduce ? 0 : 1400 })
    fitted = j.slug
  }
  function choose(slug: string, i?: number) {
    const p = current(), j = p.data.journeys.find(j => j.slug === slug)
    if (!j) return
    p.onSelectJourney(slug)
    if (i !== undefined) p.onSelectLeg(slug, i)
    fit(j)
  }
  function makeLabel(el: HTMLElement, at: [number, number], slug: string, isChecked: boolean, stop = false): Label {
    el.hidden = true
    const marker = new maplibregl.Marker({ element: el, anchor: stop ? 'left' : 'bottom', offset: stop ? [7, 0] : [0, -7] }).setLngLat(at).addTo(map)
    return { el, marker, at, slug, checked: isChecked }
  }
  function rebuildJourneys(journeys: Journey[]) {
    remove(journeyLabels)
    journeyLabels = journeys.filter(j => j.route?.length).slice().sort((a, b) => a.title.localeCompare(b.title))
      .sort((a, b) => (priority[a.status] ?? 2) - (priority[b.status] ?? 2)).map(j => {
        const el = document.createElement('button')
        el.type = 'button'; el.className = 'jl'; el.textContent = j.title
        el.addEventListener('click', ev => { ev.stopPropagation(); choose(j.slug) })
        return makeLabel(el, point(j.route[Math.floor((j.route.length - 1) / 2)]), j.slug, j.segments.some(s => checked(s.ink)))
      })
  }
  function rebuildStops(p: ChartProps) {
    remove(stopLabels)
    const j = p.data.journeys.find(j => j.slug === p.selected)
    stopLabels = j ? (j.route ?? []).map((pt, k) => {
      const el = document.createElement('span'); el.className = 'sl'; el.textContent = pt[2]
      return makeLabel(el, point(pt), j.slug, stopChecked(j, k), true)
    }) : []
  }
  function rebuildVessels(p: ChartProps) {
    remove(vesselLabels)
    vesselLabels = p.data.vehicles.flatMap(v => {
      if (!v.fix || !v.heard) return []
      const el = document.createElement('span'); el.className = 'vl'; el.textContent = vesselLabel(v)
      return [makeLabel(el, [v.fix.lon, v.fix.lat], v.journey, true)]
    })
  }
  function applyFilters(p: ChartProps) {
    const slug: maplibregl.ExpressionSpecification = ['==', ['get', 'slug'], p.selected ?? '']
    map.setFilter('halo', p.myth ? ['all', slug, CHECKED] : slug)
    for (const id of ['casing', 'hit']) map.setFilter(id, p.myth ? CHECKED : null)
    map.setFilter('stops', p.myth ? ['==', ['get', 'checked'], true] : null)
    for (const id of ['pencil-a', 'pencil-b', 'dotted']) map.setLayoutProperty(id, 'visibility', p.myth ? 'none' : 'visible')
    for (const [id, full] of [['halo', 0.28], ['pencil-a', 0.9], ['pencil-b', 0.6], ['dotted', 1], ['dashed', 1], ['heavy', 1], ['contradicted', 1], ['hit', 0.01]] as const) {
      map.setPaintProperty(id, 'line-opacity', opacity(p.focus, full))
    }
    // Keep zoom at the outermost expression, as MapLibre requires for zoom-dependent paint.
    map.setPaintProperty('casing', 'line-opacity', fadeIn(opacity(p.focus, 0.85)))
    for (const id of ['stops', 'vessels']) {
      map.setPaintProperty(id, 'circle-opacity', opacity(p.focus))
      map.setPaintProperty(id, 'circle-stroke-opacity', opacity(p.focus))
    }
  }
  function update(p: ChartProps) {
    if (!loaded) return
    if (previous?.data.journeys !== p.data.journeys) {
      (map.getSource('segs') as GeoJSONSource).setData(segments(p.data.journeys))
      ;(map.getSource('stops') as GeoJSONSource).setData(stops(p.data.journeys))
      rebuildJourneys(p.data.journeys)
    }
    if (previous?.data.vehicles !== p.data.vehicles) {
      (map.getSource('vessels') as GeoJSONSource).setData(vessels(p.data.vehicles))
      rebuildVessels(p)
    }
    if (previous?.selected !== p.selected || previous?.data.journeys !== p.data.journeys) rebuildStops(p)
    applyFilters(p)
    const selected = p.data.journeys.find(j => j.slug === p.selected)
    if (selected && fitted !== selected.slug) fit(selected)
    if (!selected) fitted = null
    previous = p
    placeLabels()
  }
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Coastlines: Natural Earth' }), 'bottom-right')
  map.touchZoomRotate.disableRotation()
  // Keyboard rotation (Shift+arrow) is separate from drag/touch rotation.
  map.keyboard.disableRotation()
  map.on('load', () => {
    loaded = true
    container.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show')
    update(current())
  })
  map.on('move', queueLabels)
  map.on('resize', queueLabels)
  map.on('click', e => {
    const feature = map.queryRenderedFeatures(e.point, { layers: ['hit'] })[0]
    const slug: unknown = feature?.properties?.slug, i: unknown = feature?.properties?.i
    if (typeof slug === 'string' && typeof i === 'number') choose(slug, i)
    else current().onSelectJourney(null)
  })
  map.on('mouseenter', 'hit', () => { map.getCanvas().style.cursor = 'pointer' })
  map.on('mouseleave', 'hit', () => { map.getCanvas().style.cursor = '' })
  const observer = new ResizeObserver(() => { map.resize(); queueLabels() })
  observer.observe(container)
  return {
    update,
    destroy() {
      observer.disconnect()
      if (frame !== null) cancelAnimationFrame(frame)
      remove(journeyLabels); remove(stopLabels); remove(vesselLabels)
      map.remove()
    },
  }
}
