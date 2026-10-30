import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import type { RideData, RideLeg } from '../types'
import { sightEntities } from './rideCard'
import { addSummitIcon, rideStyle, summitWindows, updateStoredTrack } from './rideLayers'
import 'maplibre-gl/dist/maplibre-gl.css'

export default function RideMap({ leg, position, heading, data, time }: { leg: RideLeg; position: [number, number] | null; heading: number; data: RideData; time: number }) {
  const container = useRef<HTMLDivElement>(null)
  const runtime = useRef<{ map: maplibregl.Map; marker: maplibregl.Marker; update: () => void } | null>(null)
  const latest = useRef({ position, heading, data, time })
  const following = useRef(true)
  const [follow, setFollow] = useState(true)
  const [signal, setSignal] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    latest.current = { position, heading, data, time }
    runtime.current?.update()
  }, [position, heading, data, time])
  useEffect(() => {
    if (!container.current) return
    const labels: maplibregl.Marker[] = []
    const viewLabels: { marker: maplibregl.Marker; best: [number, number]; before: [number, number]; after: [number, number]; sign: number }[] = []
    let popup: maplibregl.Popup | null = null
    let map: maplibregl.Map
    setError(''); setSignal(false); setFollow(true); following.current = true
    try {
      map = new maplibregl.Map({ container: container.current, style: rideStyle(leg),
        center: latest.current.position ?? [leg.sights.km[0]?.[4] ?? 0, leg.sights.km[0]?.[3] ?? 0], zoom: 10,
        dragRotate: false, pitchWithRotate: false, touchPitch: false, attributionControl: { compact: true } })
    } catch (e) { setError(e instanceof Error ? e.message : 'Map unavailable'); return }
    const el = document.createElement('div'); el.className = 'ride-vehicle'; el.textContent = '➤'; el.setAttribute('aria-label', data.ride.vehicle.name)
    // The glyph points east; Marker rotation is clockwise from screen up.
    const marker = new maplibregl.Marker({ element: el, rotationAlignment: 'map' })
    const update = () => {
      if (!map.isStyleLoaded()) return
      const p = latest.current
      updateStoredTrack(map, p.data.track, p.time)
      if (p.position) {
        marker.setLngLat(p.position).setRotation(p.heading - 90).addTo(map)
        if (following.current) map.jumpTo({ center: p.position })
      } else marker.remove()
    }
    const showGuide = (name: string, at: [number, number]) => {
      popup?.remove()
      const content = document.createElement('div')
      const title = document.createElement('h3'); title.textContent = name; content.append(title)
      const entries = sightEntities(name, leg.guide)
      for (const entry of entries) {
        if (entry.img?.startsWith('https://')) {
          const img = document.createElement('img'); img.src = entry.img; img.alt = entry.title; img.style.width = '100%'
          img.onerror = () => { img.hidden = true }; content.append(img)
        }
        for (const text of [entry.what, entry.history]) if (text) { const p = document.createElement('p'); p.textContent = text; content.append(p) }
        for (const link of entry.links ?? []) if (link.url.startsWith('https://')) {
          const a = document.createElement('a'); a.href = link.url; a.textContent = link.label; a.target = '_blank'; a.rel = 'noopener noreferrer'; content.append(a)
        }
      }
      if (!entries.length) { const p = document.createElement('p'); p.textContent = 'Guide unavailable for this sight.'; content.append(p) }
      popup = new maplibregl.Popup({ maxWidth: '300px', className: 'ride-guide-popup' }).setLngLat(at).setDOMContent(content).addTo(map)
    }
    const placeLabels = () => {
      for (const label of labels) label.getElement().hidden = map.getZoom() < 9
      for (const label of viewLabels) {
        const a = map.project(label.before), b = map.project(label.after), dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1
        label.marker.setOffset([-label.sign * 30 * dy / length, label.sign * 30 * dx / length])
        label.marker.getElement().hidden = map.getZoom() < 9
      }
    }
    runtime.current = { map, marker, update }
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    map.touchZoomRotate.disableRotation(); map.keyboard.disableRotation()
    map.on('load', () => {
      if (!map.hasImage('summit')) addSummitIcon(map)
      for (const w of summitWindows(leg)) {
        const label = document.createElement('span'); label.className = 'ride-summit-label'; label.textContent = w.name
        labels.push(new maplibregl.Marker({ element: label, anchor: 'left', offset: [10, 0] }).setLngLat([w.to![1], w.to![0]]).addTo(map))
      }
      for (const w of leg.sights.sights.filter(w => w.major)) {
        const label = document.createElement('button'); label.type = 'button'; label.className = 'ride-view-label'; label.textContent = w.name
        const at: [number, number] = [w.best[1], w.best[0]]
        label.onclick = e => { e.stopPropagation(); showGuide(w.name, at) }
        const near = leg.sights.km.reduce((best, row, i, rows) => Math.hypot(row[3] - w.best[0], row[4] - w.best[1]) < Math.hypot(rows[best][3] - w.best[0], rows[best][4] - w.best[1]) ? i : best, 0)
        const rowAt = (i: number): [number, number] => { const row = leg.sights.km[Math.max(0, Math.min(leg.sights.km.length - 1, i))]; return [row[4], row[3]] }
        if (leg.sights.km.length) viewLabels.push({ marker: new maplibregl.Marker({ element: label, anchor: w.side === 'left' ? 'right' : 'left' }).setLngLat(at).addTo(map), best: at, before: rowAt(near - 2), after: rowAt(near + 2), sign: w.side === 'left' ? -1 : 1 })
      }
      placeLabels()
      update()
    })
    map.on('styleimagemissing', e => { if (e.id === 'summit' && !map.hasImage('summit')) addSummitIcon(map) })
    map.on('zoom', placeLabels)
    map.on('click', 'summits', e => {
      const feature = e.features?.[0]
      if (feature?.geometry.type === 'Point') showGuide(String(feature.properties.name), feature.geometry.coordinates as [number, number])
    })
    map.on('dragstart', () => { following.current = false; setFollow(false) })
    map.on('error', () => setError('Some map imagery is unavailable. The ride card remains usable.'))
    const observer = new ResizeObserver(() => map.resize()); observer.observe(container.current)
    return () => { observer.disconnect(); labels.forEach(l => l.remove()); viewLabels.forEach(l => l.marker.remove()); popup?.remove(); marker.remove(); map.remove(); runtime.current = null }
  }, [leg, data.ride.vehicle.name])
  const toggleSignal = () => {
    const next = !signal; setSignal(next)
    const map = runtime.current?.map
    if (map?.isStyleLoaded()) for (const id of ['signal', 'measured']) map.setLayoutProperty(id, 'visibility', next ? 'visible' : 'none')
  }
  return <div className="ride-map-shell">
    <div ref={container} className="ride-map" role="region" aria-label="Ride map over Esri imagery" />
    <div className="ride-map-tools">
      <button type="button" aria-pressed={follow} onClick={() => { following.current = true; setFollow(true); runtime.current?.update() }}>Follow vehicle</button>
      {leg.coverage && <button type="button" aria-pressed={signal} onClick={toggleSignal}>Signal line</button>}
      <details open={typeof window !== 'undefined' && window.innerWidth >= 600}><summary>Map key</summary>
        <p><i className="ride-tooth large" /> Don’t miss <i className="ride-tooth" /> Worth a look</p><p>▲ Summit · dashed line of sight · views model</p>
        {signal && leg.coverage && <div>{leg.coverage.classes.map(c => <p key={c.label}><i style={{ background: c.color }} className="ride-signal-key" /> {c.label}</p>)}<p>White: measured speed tests</p></div>}
      </details>
    </div>
    {error && <p className="ride-map-error" role="status">{error}</p>}
  </div>
}
